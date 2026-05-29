"""DORA metric calculations.

This module owns the *definitions* of the four DORA metrics. Each metric
returns a dict with the raw inputs (so the dashboard can show breakdowns)
plus the headline number and the DORA performance band.

Definitions follow the DORA / "Accelerate" canon:
  - Deployment Frequency: production deployments per day.
  - Lead Time for Changes: time from first commit on a change to that change
    being deployed to production. (Falls back to merge time if no deploy is
    recorded.)
  - Change Failure Rate: % of production deployments that result in a failure
    (revert, hotfix, or production incident).
  - Mean Time to Recovery: time from incident start to resolution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.events import (
    ClaudeCodeSession, Deployment, Incident, PullRequest, WorkflowRun,
)
from app.services.stats import median, mean, percentile

PROD_ENVIRONMENTS = ("production", "prod")


def _band_from_thresholds(value: float, thresholds: list[tuple[float, str]],
                         higher_is_better: bool) -> str:
    """Map a numeric value to an Elite/High/Medium/Low band.

    `thresholds` is an ordered list of (boundary, band) pairs. For
    `higher_is_better=True`, the first threshold a value meets/exceeds wins.
    For `higher_is_better=False`, the first threshold the value is at or below
    wins.
    """
    for boundary, band in thresholds:
        if higher_is_better:
            if value >= boundary:
                return band
        else:
            if value <= boundary:
                return band
    return "Low"


class DoraCalculator:
    def __init__(self, db: Session, repo: Optional[str] = None):
        self.db = db
        self.repo = repo

    # ── helpers ────────────────────────────────────────────────────────────
    def _repo_filter(self, model):
        return model.repo == self.repo if self.repo else True

    def _prod_deploy_filter(self):
        return and_(
            self._repo_filter(Deployment),
            Deployment.environment.in_(PROD_ENVIRONMENTS),
            Deployment.status == "success",
        )

    # ── Deployment Frequency ───────────────────────────────────────────────
    def deployment_frequency(self, start: datetime, end: datetime) -> dict:
        """Production deployments per day. Falls back to merged PRs only when
        no formal deployments are recorded for the window — the response makes
        the source explicit so the UI can flag it."""
        deploy_count = self.db.query(func.count(Deployment.id)).filter(
            and_(
                self._prod_deploy_filter(),
                Deployment.deployed_at.between(start, end),
            )
        ).scalar() or 0

        merged_prs = self.db.query(func.count(PullRequest.id)).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
            )
        ).scalar() or 0

        successful_runs = self.db.query(func.count(WorkflowRun.id)).filter(
            and_(
                self._repo_filter(WorkflowRun),
                WorkflowRun.started_at.between(start, end),
                WorkflowRun.event == "push",
                WorkflowRun.head_branch == "main",
                WorkflowRun.conclusion == "success",
            )
        ).scalar() or 0

        days = max((end - start).days, 1)
        if deploy_count > 0:
            effective = deploy_count
            source = "deployments"
        else:
            effective = merged_prs
            source = "merged_prs_fallback"

        daily_rate = effective / days
        band = _band_from_thresholds(
            daily_rate,
            [(1.0, "Elite"), (1 / 7, "High"), (1 / 30, "Medium")],
            higher_is_better=True,
        )

        return {
            "metric": "deployment_frequency",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "source": source,
            "formal_deployments": deploy_count,
            "merged_prs": merged_prs,
            "successful_ci_runs_on_main": successful_runs,
            "effective_deploy_count": effective,
            "deploys_per_day": round(daily_rate, 3),
            "dora_level": band,
        }

    # ── Lead Time for Changes ─────────────────────────────────────────────
    def lead_time_for_changes(self, start: datetime, end: datetime) -> dict:
        """Time from first commit on a PR to that PR being deployed (or merged
        when no deploy can be linked)."""
        prs = self.db.query(PullRequest).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
                PullRequest.first_commit_at.isnot(None),
            )
        ).all()

        if not prs:
            return {
                "metric": "lead_time_for_changes",
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "sample_size": 0,
                "median_hours": None,
                "p95_hours": None,
                "mean_hours": None,
                "dora_level": "Unknown",
                "breakdown": {},
                "deploy_linked": 0,
                "merge_fallback": 0,
            }

        # Cache prod deploys for this period so we can attribute each merged PR
        # to the first deploy that happened after its merge_at.
        deploys = self.db.query(Deployment).filter(
            and_(
                self._prod_deploy_filter(),
                Deployment.deployed_at >= start,
                # Deploys can land slightly past `end`; allow a 7d grace so
                # PRs near the window edge still pick up their deploy.
                Deployment.deployed_at <= end + timedelta(days=7),
            )
        ).order_by(Deployment.deployed_at.asc()).all()

        lead_times: list[float] = []
        coding_times: list[float] = []
        review_times: list[float] = []
        deploy_linked = 0
        merge_fallback = 0

        for pr in prs:
            end_ts = _first_deploy_after(deploys, pr)
            if end_ts is not None:
                deploy_linked += 1
            else:
                end_ts = pr.merged_at
                merge_fallback += 1

            total_hours = (end_ts - pr.first_commit_at).total_seconds() / 3600
            if total_hours < 0:
                # Data anomaly (e.g. deploy deployed_at predates first commit due
                # to backfill). Skip rather than poison the percentiles.
                continue
            lead_times.append(total_hours)

            if pr.created_at and pr.first_commit_at:
                coding_times.append(
                    (pr.created_at - pr.first_commit_at).total_seconds() / 3600
                )
            if pr.merged_at and pr.created_at:
                review_times.append(
                    (pr.merged_at - pr.created_at).total_seconds() / 3600
                )

        if not lead_times:
            return {
                "metric": "lead_time_for_changes",
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "sample_size": 0,
                "median_hours": None,
                "p95_hours": None,
                "mean_hours": None,
                "dora_level": "Unknown",
                "breakdown": {},
                "deploy_linked": deploy_linked,
                "merge_fallback": merge_fallback,
            }

        med = median(lead_times)
        p95 = percentile(lead_times, 95)
        avg = mean(lead_times)
        band = _band_from_thresholds(
            med,
            [(24, "Elite"), (24 * 7, "High"), (24 * 30, "Medium")],
            higher_is_better=False,
        )

        return {
            "metric": "lead_time_for_changes",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "sample_size": len(lead_times),
            "median_hours": _round(med, 2),
            "p95_hours": _round(p95, 2),
            "mean_hours": _round(avg, 2),
            "dora_level": band,
            "breakdown": {
                "coding_time_median_hours": _round(median(coding_times), 2),
                "review_time_median_hours": _round(median(review_times), 2),
            },
            "deploy_linked": deploy_linked,
            "merge_fallback": merge_fallback,
        }

    # ── Change Failure Rate ───────────────────────────────────────────────
    def change_failure_rate(self, start: datetime, end: datetime) -> dict:
        """% of production deployments that resulted in a failure.

        Failure = revert PR, hotfix PR, or correlated incident inside the
        window. CI failure rate is reported alongside as a *separate* metric,
        not as the primary CFR — DORA defines CFR over deployments, not CI runs.
        """
        deploy_count = self.db.query(func.count(Deployment.id)).filter(
            and_(
                self._prod_deploy_filter(),
                Deployment.deployed_at.between(start, end),
            )
        ).scalar() or 0

        merged = self.db.query(func.count(PullRequest.id)).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
            )
        ).scalar() or 0

        reverts = self.db.query(func.count(PullRequest.id)).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
                PullRequest.is_revert.is_(True),
            )
        ).scalar() or 0

        hotfixes = self.db.query(func.count(PullRequest.id)).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
                PullRequest.is_hotfix.is_(True),
            )
        ).scalar() or 0

        incidents = self.db.query(func.count(Incident.id)).filter(
            and_(
                self._repo_filter(Incident),
                Incident.started_at.between(start, end),
            )
        ).scalar() or 0

        total_runs = self.db.query(func.count(WorkflowRun.id)).filter(
            and_(
                self._repo_filter(WorkflowRun),
                WorkflowRun.started_at.between(start, end),
                WorkflowRun.event == "push",
                WorkflowRun.head_branch == "main",
            )
        ).scalar() or 0

        failed_runs = self.db.query(func.count(WorkflowRun.id)).filter(
            and_(
                self._repo_filter(WorkflowRun),
                WorkflowRun.started_at.between(start, end),
                WorkflowRun.event == "push",
                WorkflowRun.head_branch == "main",
                WorkflowRun.conclusion == "failure",
            )
        ).scalar() or 0

        ci_failure_rate = (failed_runs / total_runs * 100) if total_runs else 0.0
        failures = reverts + hotfixes + incidents

        if deploy_count > 0:
            cfr = failures / deploy_count * 100
            source = "deployments"
        elif merged > 0:
            cfr = failures / merged * 100
            source = "merged_prs_fallback"
        else:
            cfr = 0.0
            source = "no_data"

        # CFR is bounded — clip extreme values from data anomalies (e.g. one
        # deploy and three hotfixes inside the same hour).
        cfr = min(cfr, 100.0)

        band = _band_from_thresholds(
            cfr,
            [(5, "Elite"), (10, "High"), (15, "Medium")],
            higher_is_better=False,
        )

        return {
            "metric": "change_failure_rate",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "source": source,
            "deployments": deploy_count,
            "total_merged_prs": merged,
            "reverts": reverts,
            "hotfixes": hotfixes,
            "incidents": incidents,
            "failures": failures,
            "cfr_pct": round(cfr, 2),
            "ci_total_runs": total_runs,
            "ci_failed_runs": failed_runs,
            "ci_failure_rate_pct": round(ci_failure_rate, 2),
            # `combined_cfr_pct` retained for frontend backward compat.
            "combined_cfr_pct": round(cfr, 2),
            "dora_level": band,
        }

    # ── Mean Time to Recovery ─────────────────────────────────────────────
    def mean_time_to_recovery(self, start: datetime, end: datetime) -> dict:
        resolved = self.db.query(Incident).filter(
            and_(
                self._repo_filter(Incident),
                Incident.started_at.between(start, end),
                Incident.resolved_at.isnot(None),
            )
        ).all()

        incident_hours = [
            (i.resolved_at - i.started_at).total_seconds() / 3600
            for i in resolved
            if i.resolved_at and i.started_at and i.resolved_at >= i.started_at
        ]

        hotfix_prs = self.db.query(PullRequest).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
                PullRequest.is_hotfix.is_(True),
                PullRequest.created_at.isnot(None),
                PullRequest.merged_at.isnot(None),
            )
        ).all()

        hotfix_hours = [
            (pr.merged_at - pr.created_at).total_seconds() / 3600
            for pr in hotfix_prs
            if pr.merged_at >= pr.created_at
        ]

        all_recovery = incident_hours + hotfix_hours

        if not all_recovery:
            return {
                "metric": "mean_time_to_recovery",
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "sample_size": 0,
                "from_incidents": 0,
                "from_hotfix_prs": 0,
                "median_hours": None,
                "mean_hours": None,
                "p95_hours": None,
                "dora_level": "Unknown",
            }

        med = median(all_recovery)
        avg = mean(all_recovery)
        p95 = percentile(all_recovery, 95)
        band = _band_from_thresholds(
            med,
            [(1, "Elite"), (24, "High"), (24 * 7, "Medium")],
            higher_is_better=False,
        )

        return {
            "metric": "mean_time_to_recovery",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "sample_size": len(all_recovery),
            "from_incidents": len(incident_hours),
            "from_hotfix_prs": len(hotfix_hours),
            "median_hours": _round(med, 2),
            "mean_hours": _round(avg, 2),
            "p95_hours": _round(p95, 2),
            "dora_level": band,
        }

    # ── Claude Code ───────────────────────────────────────────────────────
    def claude_code_metrics(self, start: datetime, end: datetime) -> dict:
        sessions = self.db.query(ClaudeCodeSession).filter(
            ClaudeCodeSession.session_date.between(start, end),
        ).all()

        if not sessions:
            return {
                "metric": "claude_code",
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "total_sessions": 0,
            }

        total_sessions = sum(s.num_sessions or 0 for s in sessions)
        total_loc_added = sum(s.lines_added or 0 for s in sessions)
        total_loc_removed = sum(s.lines_removed or 0 for s in sessions)
        total_commits = sum(s.commits_created or 0 for s in sessions)
        total_prs = sum(s.prs_created or 0 for s in sessions)
        total_accepted = sum(s.edit_accepted or 0 for s in sessions)
        total_rejected = sum(s.edit_rejected or 0 for s in sessions)
        total_cost_cents = sum(s.estimated_cost_cents or 0 for s in sessions)

        decisions = total_accepted + total_rejected
        acceptance_rate = (total_accepted / decisions * 100) if decisions else 0.0

        return {
            "metric": "claude_code",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "total_sessions": total_sessions,
            "lines_of_code": {"added": total_loc_added, "removed": total_loc_removed},
            "commits_created": total_commits,
            "prs_created": total_prs,
            "edits_accepted": total_accepted,
            "edits_rejected": total_rejected,
            "acceptance_rate_pct": round(acceptance_rate, 2),
            "total_cost_usd": round(total_cost_cents / 100, 2),
            "unique_users": len({s.user_email for s in sessions if s.user_email}),
        }

    def summary(self, start: datetime, end: datetime) -> dict:
        return {
            "deployment_frequency": self.deployment_frequency(start, end),
            "lead_time_for_changes": self.lead_time_for_changes(start, end),
            "change_failure_rate": self.change_failure_rate(start, end),
            "mean_time_to_recovery": self.mean_time_to_recovery(start, end),
            "claude_code": self.claude_code_metrics(start, end),
        }

    # ── Weekly timeline ───────────────────────────────────────────────────
    def weekly_timeline(self, weeks: int) -> list[dict]:
        """Return one row per week for the last `weeks` weeks (oldest first).

        Computed in Python after a *single* bulk fetch per table — avoids the
        N×4 query pattern of running `summary()` once per week (which was the
        previous shape and pegged Postgres on long ranges).
        """
        if weeks < 1:
            return []

        end = datetime.now(timezone.utc)
        start = end - timedelta(weeks=weeks)

        deploys = self.db.query(Deployment.deployed_at).filter(
            and_(
                self._prod_deploy_filter(),
                Deployment.deployed_at.between(start, end),
            )
        ).all()

        prs = self.db.query(
            PullRequest.merged_at,
            PullRequest.first_commit_at,
            PullRequest.is_revert,
            PullRequest.is_hotfix,
        ).filter(
            and_(
                self._repo_filter(PullRequest),
                PullRequest.merged_at.between(start, end),
            )
        ).all()

        incidents = self.db.query(
            Incident.started_at, Incident.resolved_at,
        ).filter(
            and_(
                self._repo_filter(Incident),
                Incident.started_at.between(start, end),
            )
        ).all()

        buckets: list[dict] = []
        for w in range(weeks):
            ws = end - timedelta(weeks=w + 1)
            we = end - timedelta(weeks=w)
            buckets.append({
                "week_start": ws,
                "week_end": we,
                "_deploys": 0,
                "_lead_hours": [],
                "_failures": 0,
                "_recovery_hours": [],
                "_merged": 0,
            })

        def _find_bucket(t: Optional[datetime]) -> Optional[dict]:
            if t is None:
                return None
            # Buckets are ordered newest → oldest. Linear scan is fine for
            # small `weeks` counts (the route caps at MAX_DAYS/7).
            for b in buckets:
                if b["week_start"] <= t < b["week_end"]:
                    return b
            return None

        for (deployed_at,) in deploys:
            b = _find_bucket(deployed_at)
            if b is not None:
                b["_deploys"] += 1

        for merged_at, first_commit_at, is_revert, is_hotfix in prs:
            b = _find_bucket(merged_at)
            if b is None:
                continue
            b["_merged"] += 1
            if first_commit_at is not None:
                hrs = (merged_at - first_commit_at).total_seconds() / 3600
                if hrs >= 0:
                    b["_lead_hours"].append(hrs)
            if is_revert or is_hotfix:
                b["_failures"] += 1

        for started_at, resolved_at in incidents:
            b = _find_bucket(started_at)
            if b is None:
                continue
            b["_failures"] += 1
            if resolved_at is not None and resolved_at >= started_at:
                b["_recovery_hours"].append(
                    (resolved_at - started_at).total_seconds() / 3600
                )

        # Fallback decision is window-wide so the trend is internally
        # consistent (we don't want some weeks counting deploys and other
        # weeks counting merged PRs — that produces misleading kinks). If
        # the whole window has zero formal deployments, switch the trend
        # to the merged-PR proxy and tag the response with the source so
        # the UI can label it. This matches `summary().deployment_frequency`.
        total_deploys = sum(b["_deploys"] for b in buckets)
        source = "deployments" if total_deploys > 0 else "merged_prs_fallback"

        out: list[dict] = []
        # oldest → newest for charting
        for b in reversed(buckets):
            effective = b["_deploys"] if source == "deployments" else b["_merged"]
            denom = effective
            cfr = (b["_failures"] / denom * 100) if denom else 0.0
            out.append({
                "week_start": b["week_start"].isoformat(),
                "week_end": b["week_end"].isoformat(),
                "deployment_frequency": round(effective / 7, 3),
                "lead_time_hours": _round(median(b["_lead_hours"]), 2),
                "change_failure_rate": round(min(cfr, 100.0), 2),
                "mttr_hours": _round(median(b["_recovery_hours"]), 2),
                "source": source,
            })
        return out


# ── module helpers ────────────────────────────────────────────────────────
def _round(v, ndigits):
    return round(v, ndigits) if v is not None else None


def _first_deploy_after(deploys: list[Deployment], pr: PullRequest) -> Optional[datetime]:
    """Find the first prod deploy whose deployed_at is at or after pr.merged_at.

    `deploys` must be ascending-sorted on deployed_at. We use a linear scan;
    typical PR counts per window keep this O(n*m) but n*m is small (< 10k).
    For larger volumes a bisect would be a drop-in upgrade.
    """
    if pr.merged_at is None:
        return None
    for d in deploys:
        if d.deployed_at and d.deployed_at >= pr.merged_at:
            return d.deployed_at
    return None
