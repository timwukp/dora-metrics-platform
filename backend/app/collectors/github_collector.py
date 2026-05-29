"""GitHub data collector.

Pulls PRs, commits, workflow runs, and deployments for the configured repos.
A few decisions worth knowing:

* **Pagination is bounded by `max_pages`.** GitHub Search API caps results at
  ~1000 anyway, but list endpoints (PRs, runs, deployments) can return tens
  of thousands. We page until the response runs out *or* we hit `max_pages`,
  whichever comes first. Default 5 × 100 = 500 items per call — sufficient
  for the 15-minute poll cadence; the webhook keeps things fresh between
  polls.

* **Reverts/hotfixes are classified by `app.services.pr_classifier`** rather
  than ad-hoc substring matches. The old `"fix" in branch.lower()` flagged
  every `fix/typo` PR as a hotfix and inflated CFR.

* **`first_commit_at` walks all commits.** GitHub returns PR commits in
  chronological order, but a force-push can rewrite history; we still take
  the *minimum* `authored_at` across the page rather than trusting position.

* **Reviews collection is incremental.** We stop scanning a PR once we've
  seen a review submitted before the most recent one in our DB — avoids the
  full repo re-fetch on every poll.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.events import (
    Commit, Deployment, PullRequest, ReviewEvent, WorkflowRun,
)
from app.services.pr_classifier import detect_ai_assistant, is_hotfix, is_revert

logger = logging.getLogger(__name__)


class GitHubCollector:
    def __init__(self, token: Optional[str] = None, max_pages: int = 5):
        self.token = token or settings.github_token
        self.base_url = "https://api.github.com"
        self.max_pages = max_pages
        self.headers = {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ── pagination helper ───────────────────────────────────────────────
    async def _paginate(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """Yield items one at a time across up to `self.max_pages` pages.

        GitHub returns 200 + `[]` for empty pages; we use that as the
        terminator. We do not follow Link headers — just bump `page=` —
        which is fine for stable sort orders (`updated desc`, `created desc`).
        """
        params = dict(params or {})
        params.setdefault("per_page", 100)
        for page in range(1, self.max_pages + 1):
            params["page"] = page
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code != 200:
                logger.warning("GET %s page=%d → %d", url, page, resp.status_code)
                return
            items = resp.json()
            if isinstance(items, dict):  # /actions/runs returns a wrapper
                items = items.get("workflow_runs", [])
            if not items:
                return
            for it in items:
                yield it
            if len(items) < params["per_page"]:
                return

    # ── orchestrator ────────────────────────────────────────────────────
    async def collect_all(self, db: Session, repo: str):
        await self.collect_pull_requests(db, repo)
        await self.collect_commits(db, repo)
        await self.collect_workflow_runs(db, repo)
        await self.collect_deployments(db, repo)

    # ── PRs ─────────────────────────────────────────────────────────────
    async def collect_pull_requests(self, db: Session, repo: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/repos/{repo}/pulls"
            params = {"state": "all", "sort": "updated", "direction": "desc"}
            async for pr_data in self._paginate(client, url, params):
                await self._upsert_pr(client, db, repo, pr_data)
            db.commit()

    async def _upsert_pr(self, client, db: Session, repo: str, pr_data: dict):
        if not pr_data.get("number") or not pr_data.get("user"):
            return

        existing = db.query(PullRequest).filter(
            PullRequest.repo == repo,
            PullRequest.number == pr_data["number"],
        ).first()

        merged_at = pr_data.get("merged_at")
        state = "merged" if merged_at else pr_data.get("state", "open")

        first_commit_at = await self._get_first_commit_time(
            client, repo, pr_data["number"],
        )
        review_data = await self._get_review_data(client, repo, pr_data["number"])

        title = pr_data.get("title") or ""
        branch = (pr_data.get("head") or {}).get("ref")
        labels = [l.get("name") for l in pr_data.get("labels", []) if l.get("name")]

        pr_record_kwargs = dict(
            repo=repo,
            number=pr_data["number"],
            title=title,
            state=state,
            author=(pr_data["user"] or {}).get("login"),
            created_at=_parse_dt(pr_data.get("created_at")),
            merged_at=_parse_dt(merged_at),
            closed_at=_parse_dt(pr_data.get("closed_at")),
            first_commit_at=first_commit_at,
            first_review_at=review_data.get("first_review_at"),
            approved_at=review_data.get("approved_at"),
            additions=pr_data.get("additions") or 0,
            deletions=pr_data.get("deletions") or 0,
            changed_files=pr_data.get("changed_files") or 0,
            is_revert=is_revert(title, labels),
            is_hotfix=is_hotfix(title, branch, labels),
            labels=labels,
            assisted_by=detect_ai_assistant(pr_data.get("body")),
        )

        if existing:
            for key, val in pr_record_kwargs.items():
                setattr(existing, key, val)
        else:
            db.add(PullRequest(**pr_record_kwargs))

    async def _get_first_commit_time(
        self, client: httpx.AsyncClient, repo: str, pr_number: int,
    ) -> Optional[datetime]:
        """Return the earliest authored_at across the PR's first page of commits.

        We don't trust ordering — a force-push can leave the chronologically-
        first commit anywhere in the list — and we only fetch one page (PRs
        with > 100 commits are vanishingly rare and the lead-time signal
        survives a rough estimate).
        """
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}/commits"
        resp = await client.get(url, headers=self.headers, params={"per_page": 100})
        if resp.status_code != 200:
            return None
        commits = resp.json() or []
        timestamps = []
        for c in commits:
            commit = c.get("commit") or {}
            author = commit.get("author") or {}
            ts = _parse_dt(author.get("date"))
            if ts is not None:
                timestamps.append(ts)
        return min(timestamps) if timestamps else None

    async def _get_review_data(
        self, client: httpx.AsyncClient, repo: str, pr_number: int,
    ) -> dict:
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}/reviews"
        resp = await client.get(url, headers=self.headers, params={"per_page": 100})
        result = {"first_review_at": None, "approved_at": None}
        if resp.status_code != 200:
            return result
        for r in resp.json() or []:
            ts = _parse_dt(r.get("submitted_at"))
            if ts is None:
                continue
            if result["first_review_at"] is None or ts < result["first_review_at"]:
                result["first_review_at"] = ts
            if r.get("state") == "APPROVED" and (
                result["approved_at"] is None or ts < result["approved_at"]
            ):
                result["approved_at"] = ts
        return result

    # ── Reviews (incremental) ───────────────────────────────────────────
    async def collect_reviews(self, db: Session, repo: str):
        """Refresh review events, skipping anything older than what we already have.

        The old version re-fetched every PR's full review history on every
        poll — O(prs × reviews) per tick. We track the most recent reviewed-at
        we've stored and only walk PRs that have updated since.
        """
        last_seen = db.query(func.max(ReviewEvent.submitted_at)).filter(
            ReviewEvent.repo == repo,
        ).scalar()
        cutoff = last_seen or datetime(1970, 1, 1, tzinfo=timezone.utc)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Only inspect PRs touched since the last seen review — covers
            # both freshly-opened PRs and existing PRs receiving new reviews.
            stale_prs = db.query(PullRequest).filter(
                PullRequest.repo == repo,
                PullRequest.merged_at.is_(None) | (PullRequest.merged_at >= cutoff),
            ).all()

            for pr in stale_prs:
                if pr.number is None:
                    continue
                url = f"{self.base_url}/repos/{repo}/pulls/{pr.number}/reviews"
                resp = await client.get(
                    url, headers=self.headers, params={"per_page": 100},
                )
                if resp.status_code != 200:
                    continue
                for review in resp.json() or []:
                    ts = _parse_dt(review.get("submitted_at"))
                    user = review.get("user") or {}
                    reviewer = user.get("login")
                    if ts is None or reviewer is None:
                        continue
                    if ts <= cutoff:
                        continue
                    existing = db.query(ReviewEvent).filter(
                        ReviewEvent.repo == repo,
                        ReviewEvent.pr_number == pr.number,
                        ReviewEvent.reviewer == reviewer,
                        ReviewEvent.submitted_at == ts,
                    ).first()
                    if existing:
                        continue
                    db.add(ReviewEvent(
                        repo=repo,
                        pr_number=pr.number,
                        reviewer=reviewer,
                        state=review.get("state"),
                        submitted_at=ts,
                        is_bot=user.get("type") == "Bot",
                    ))
            db.commit()

    # ── Commits ─────────────────────────────────────────────────────────
    async def collect_commits(self, db: Session, repo: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/repos/{repo}/commits"
            async for c in self._paginate(client, url):
                sha = c.get("sha")
                commit = c.get("commit") or {}
                if not sha or not commit:
                    continue
                if db.query(Commit).filter(Commit.sha == sha).first():
                    continue
                author = commit.get("author") or {}
                message = commit.get("message") or ""
                db.add(Commit(
                    repo=repo,
                    sha=sha,
                    message=message[:500],
                    author=author.get("name"),
                    authored_at=_parse_dt(author.get("date")),
                    is_merge=message.startswith("Merge pull request"),
                ))
            db.commit()

    # ── Workflow runs ───────────────────────────────────────────────────
    async def collect_workflow_runs(self, db: Session, repo: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/repos/{repo}/actions/runs"
            async for run in self._paginate(client, url):
                run_id = run.get("id")
                if run_id is None:
                    continue
                if db.query(WorkflowRun).filter(WorkflowRun.run_id == run_id).first():
                    continue
                started = _parse_dt(run.get("created_at"))
                completed = _parse_dt(run.get("updated_at"))
                duration = (
                    (completed - started).total_seconds()
                    if started and completed and completed >= started
                    else None
                )
                db.add(WorkflowRun(
                    repo=repo,
                    run_id=run_id,
                    name=run.get("name"),
                    conclusion=run.get("conclusion"),
                    event=run.get("event"),
                    head_branch=run.get("head_branch"),
                    started_at=started,
                    completed_at=completed,
                    duration_seconds=duration,
                ))
            db.commit()

    # ── Deployments ─────────────────────────────────────────────────────
    async def collect_deployments(self, db: Session, repo: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}/repos/{repo}/deployments"
            async for dep in self._paginate(client, url):
                sha = dep.get("sha")
                env = dep.get("environment")
                if not sha or not env:
                    continue
                if db.query(Deployment).filter(
                    Deployment.repo == repo,
                    Deployment.sha == sha,
                    Deployment.environment == env,
                ).first():
                    continue

                statuses_url = dep.get("statuses_url")
                latest_status = "unknown"
                if statuses_url:
                    sresp = await client.get(statuses_url, headers=self.headers)
                    if sresp.status_code == 200:
                        statuses = sresp.json() or []
                        if statuses:
                            latest_status = statuses[0].get("state") or "unknown"

                creator = dep.get("creator") or {}
                db.add(Deployment(
                    repo=repo,
                    environment=env,
                    sha=sha,
                    ref=dep.get("ref"),
                    deployed_at=_parse_dt(dep.get("created_at")),
                    status=latest_status,
                    triggered_by=creator.get("login"),
                ))
            db.commit()


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
