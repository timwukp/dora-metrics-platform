"""HTTP API surface for the DORA platform.

A few cross-cutting concerns worth knowing:

* **Background tasks own their own DB session.** FastAPI's `Depends(get_db)`
  yields a session that closes when the request ends, but `BackgroundTasks`
  run *after* the response is returned — using a request-scoped session there
  causes "session is closed" errors under load. Each background task here
  opens its own `SessionLocal()` and closes it in `finally`.

* **Webhook replay protection.** GitHub may retry a delivery (transient 5xx,
  network blip) and a malicious actor with a leaked secret could replay an
  older payload. We dedupe on `X-GitHub-Delivery` via the `webhook_deliveries`
  table; second sightings return 200 no-op so the sender stops retrying.

* **`/health/live` vs `/health/ready`.** Liveness is "process is up";
  readiness is "process is up *and* the DB is reachable". K8s uses these
  separately — failing readiness pulls the pod from the Service, failing
  liveness restarts it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.security import require_api_key, verify_github_signature
from app.collectors.claude_code_collector import ClaudeCodeCollector
from app.collectors.github_collector import GitHubCollector
from app.config.settings import settings
from app.models.database import SessionLocal, get_db
from app.models.events import (
    AlertEvent, AlertRule, ReviewEvent, WebhookDelivery,
)
from app.services.alerts import evaluate_all as evaluate_all_alerts, evaluate_repo as evaluate_alerts_for_repo
from app.services.dora_calculator import DoraCalculator
from app.services.level_history import (
    list_snapshots as list_level_snapshots,
    snapshot_recent_weeks,
)
from app.services.retro import render_markdown as render_retro_markdown

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

MAX_DAYS = 730  # cap query window to 2 years to avoid runaway DB scans


# ── helpers ───────────────────────────────────────────────────────────────
def _default_repo() -> str:
    repos = settings.github_repo_list
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No repositories configured (set DORA_GITHUB_REPOS).",
        )
    return repos[0]


def _validate_repo(repo: Optional[str]) -> str:
    """Ensure caller can only query repos this server is configured to track."""
    allowed = settings.github_repo_list
    if repo is None:
        return _default_repo()
    if repo not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Repo not configured. Allowed: {allowed}",
        )
    return repo


def _parse_range(start: Optional[str], end: Optional[str], days: int):
    if days < 1 or days > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"days must be 1..{MAX_DAYS}")
    try:
        end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
        start_dt = datetime.fromisoformat(start) if start else end_dt - timedelta(days=days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date: {e}")
    if start_dt >= end_dt:
        raise HTTPException(status_code=400, detail="start must be before end")
    if (end_dt - start_dt).days > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"range too large (>{MAX_DAYS} days)")
    return start_dt, end_dt


def _run_with_session(coro_factory, *args, label: str):
    """Run an async collector function with its own DB session lifecycle.

    `coro_factory` is the bound method (e.g. `collector.collect_pull_requests`).
    We open a fresh `SessionLocal()` here — never reuse the request session —
    and close it in `finally`. Exceptions are logged and swallowed so a single
    failed task doesn't kill the worker.
    """
    import asyncio  # local import — only needed in the background path

    db = SessionLocal()
    try:
        asyncio.run(coro_factory(db, *args))
    except Exception:
        logger.exception("background task %s failed", label)
    finally:
        db.close()


# ── DORA metrics ──────────────────────────────────────────────────────────
@router.get("/metrics/dora")
def get_dora_summary(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db, repo=_validate_repo(repo)).summary(start_dt, end_dt)


@router.get("/metrics/deploy-freq")
def get_deployment_frequency(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db, repo=_validate_repo(repo)).deployment_frequency(start_dt, end_dt)


@router.get("/metrics/lead-time")
def get_lead_time(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db, repo=_validate_repo(repo)).lead_time_for_changes(start_dt, end_dt)


@router.get("/metrics/change-fail")
def get_change_failure_rate(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db, repo=_validate_repo(repo)).change_failure_rate(start_dt, end_dt)


@router.get("/metrics/mttr")
def get_mttr(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db, repo=_validate_repo(repo)).mean_time_to_recovery(start_dt, end_dt)


@router.get("/metrics/claude-code")
def get_claude_code_metrics(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_range(start, end, days)
    return DoraCalculator(db).claude_code_metrics(start_dt, end_dt)


# Sprint retro export (issue #18)
@router.get("/reports/retro")
def get_retro_report(
    repo: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(14, ge=1, le=MAX_DAYS),
    sprint_label: Optional[str] = Query(None, max_length=80),
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    db: Session = Depends(get_db),
):
    """Render a retro report for the given window.

    Returns Markdown by default (text/markdown) so a `Save as` from the
    browser produces a usable file. Pass `format=json` to get the underlying
    DORA summary alongside the rendered Markdown — useful when the dashboard
    wants to render it inline before downloading.
    """
    from fastapi.responses import PlainTextResponse

    start_dt, end_dt = _parse_range(start, end, days)
    repo_resolved = _validate_repo(repo)
    summary = DoraCalculator(db, repo=repo_resolved).summary(start_dt, end_dt)
    md = render_retro_markdown(repo_resolved, summary, sprint_label=sprint_label)
    if format == "json":
        return {"repo": repo_resolved, "markdown": md, "summary": summary}
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")


@router.get("/metrics/timeline")
def get_timeline(
    repo: Optional[str] = Query(None),
    days: int = Query(90, ge=7, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    """Weekly DORA metrics for trend charts.

    Implemented as a single bulk fetch per table inside `weekly_timeline`,
    rather than re-running `summary()` once per week (which was 4 queries
    × `weeks` weeks).
    """
    repo = _validate_repo(repo)
    weeks = days // 7
    timeline = DoraCalculator(db, repo=repo).weekly_timeline(weeks)
    return {"timeline": timeline}


# ── Reviews ───────────────────────────────────────────────────────────────
@router.get("/reviews")
def get_reviews(
    repo: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: Session = Depends(get_db),
):
    repo = _validate_repo(repo)
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    reviews = db.query(ReviewEvent).filter(
        ReviewEvent.repo == repo,
        ReviewEvent.submitted_at >= start_dt,
    ).all()
    bot = [r for r in reviews if r.is_bot]
    human = [r for r in reviews if not r.is_bot]
    return {
        "total_reviews": len(reviews),
        "bot_reviews": len(bot),
        "human_reviews": len(human),
        "approvals": len([r for r in reviews if r.state == "APPROVED"]),
        "changes_requested": len([r for r in reviews if r.state == "CHANGES_REQUESTED"]),
        "comments_only": len([r for r in reviews if r.state == "COMMENTED"]),
        "reviewers": sorted({r.reviewer for r in reviews if r.reviewer}),
    }


# ── Manual triggers ───────────────────────────────────────────────────────
def _bg_collect_all(repo: str):
    _run_with_session(GitHubCollector().collect_all, repo, label=f"collect_all:{repo}")


def _bg_collect_prs(repo: str):
    _run_with_session(
        GitHubCollector().collect_pull_requests, repo, label=f"collect_prs:{repo}",
    )


def _bg_collect_runs(repo: str):
    _run_with_session(
        GitHubCollector().collect_workflow_runs, repo, label=f"collect_runs:{repo}",
    )


def _bg_collect_deploys(repo: str):
    _run_with_session(
        GitHubCollector().collect_deployments, repo, label=f"collect_deploys:{repo}",
    )


def _bg_collect_claude_code(start: str):
    _run_with_session(
        ClaudeCodeCollector().collect, start, label=f"claude_code:{start}",
    )


@router.post("/collect/github", dependencies=[Depends(require_api_key)])
async def trigger_github_collection(background_tasks: BackgroundTasks):
    repos = settings.github_repo_list
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No repositories configured.",
        )
    for repo in repos:
        background_tasks.add_task(_bg_collect_all, repo)
    return {"status": "collection_started", "repos": repos}


@router.post("/collect/claude-code", dependencies=[Depends(require_api_key)])
async def trigger_claude_code_collection(
    background_tasks: BackgroundTasks,
    days: int = Query(30, ge=1, le=MAX_DAYS),
):
    if not settings.claude_code_admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Claude Code admin key not configured.",
        )
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    background_tasks.add_task(_bg_collect_claude_code, start)
    return {"status": "collection_started", "starting_at": start}


# ── GitHub webhook (with replay protection) ──────────────────────────────
@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    body: bytes = Depends(verify_github_signature),
):
    """Receive a GitHub webhook event. HMAC verification is mandatory.

    Replay protection: GitHub sends a unique `X-GitHub-Delivery` UUID per
    delivery (retries reuse the same UUID). We insert it into
    `webhook_deliveries`; an `IntegrityError` on the unique constraint tells
    us this is a duplicate and we no-op with 200 (so GitHub stops retrying).
    """
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery")

    db.add(WebhookDelivery(source="github", delivery_id=delivery_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "delivery_id": delivery_id}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = request.headers.get("X-GitHub-Event")
    repo_name = (payload.get("repository") or {}).get("full_name")

    if not repo_name or repo_name not in settings.github_repo_list:
        raise HTTPException(status_code=403, detail="Repository not allowed")

    if event_type == "pull_request":
        background_tasks.add_task(_bg_collect_prs, repo_name)
    elif event_type == "workflow_run":
        background_tasks.add_task(_bg_collect_runs, repo_name)
    elif event_type == "deployment_status":
        background_tasks.add_task(_bg_collect_deploys, repo_name)
    # Unknown events are accepted-but-ignored (GitHub retries 4xx, not 2xx).

    return {"status": "accepted", "event": event_type}


# ── DORA level history (issue #16) ────────────────────────────────────────
@router.get("/metrics/level-history")
def get_level_history(
    repo: Optional[str] = Query(None),
    weeks: int = Query(26, ge=1, le=104),
    db: Session = Depends(get_db),
):
    """Return weekly DORA-level snapshots for the trailing `weeks` weeks.

    Empty list is a normal response — there's no snapshot until at least
    one week has rolled over with the scheduler running. Operators can
    bootstrap with POST /collect/level-snapshots.
    """
    repo_resolved = _validate_repo(repo)
    return {
        "repo": repo_resolved,
        "weeks": weeks,
        "snapshots": list_level_snapshots(db, repo_resolved, weeks=weeks),
    }


@router.post(
    "/collect/level-snapshots",
    dependencies=[Depends(require_api_key)],
)
def trigger_level_snapshot(
    repo: Optional[str] = Query(None),
    weeks: int = Query(1, ge=1, le=52),
    db: Session = Depends(get_db),
):
    """Compute snapshots for the trailing `weeks` completed weeks. Idempotent.
    Used to bootstrap the timeline on a fresh database."""
    repo_resolved = _validate_repo(repo)
    touched = snapshot_recent_weeks(db, repo_resolved, weeks=weeks)
    return {"repo": repo_resolved, "weeks": weeks, "rows_touched": touched}


# ── Alerts (issue #15) ────────────────────────────────────────────────────
_ALLOWED_METRICS = {
    "deployment_frequency", "lead_time_for_changes",
    "change_failure_rate", "mean_time_to_recovery",
}
_ALLOWED_OPS = {">", "<", ">=", "<="}
_ALLOWED_CHANNELS = {"slack", "email"}


def _validate_alert_rule_payload(p: dict) -> dict:
    repo = _validate_repo(p.get("repo"))
    metric = p.get("metric")
    if metric not in _ALLOWED_METRICS:
        raise HTTPException(400, f"metric must be one of {sorted(_ALLOWED_METRICS)}")
    op = p.get("operator")
    if op not in _ALLOWED_OPS:
        raise HTTPException(400, f"operator must be one of {sorted(_ALLOWED_OPS)}")
    try:
        threshold = float(p["threshold"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "threshold must be a number")
    change_pct = p.get("change_pct")
    if change_pct is not None:
        try:
            change_pct = float(change_pct)
        except (ValueError, TypeError):
            raise HTTPException(400, "change_pct must be a number or null")
    channels_raw = p.get("channels", "slack")
    channels = [c.strip() for c in channels_raw.split(",") if c.strip()]
    if not channels:
        raise HTTPException(400, "at least one channel required")
    bad = [c for c in channels if c not in _ALLOWED_CHANNELS]
    if bad:
        raise HTTPException(400, f"unknown channels: {bad}")
    return {
        "repo": repo, "metric": metric, "operator": op,
        "threshold": threshold, "change_pct": change_pct,
        "channels": ",".join(channels),
        "enabled": bool(p.get("enabled", True)),
    }


@router.get("/alerts/rules")
def list_alert_rules(db: Session = Depends(get_db)):
    rows = db.query(AlertRule).order_by(AlertRule.created_at.desc()).all()
    return {"rules": [
        {
            "id": r.id, "repo": r.repo, "metric": r.metric,
            "operator": r.operator, "threshold": r.threshold,
            "change_pct": r.change_pct, "channels": r.channels,
            "enabled": r.enabled,
        } for r in rows
    ]}


@router.post("/alerts/rules", dependencies=[Depends(require_api_key)])
async def create_alert_rule(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    fields = _validate_alert_rule_payload(payload)
    rule = AlertRule(**fields)
    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "rule already exists for this (repo, metric)")
    db.refresh(rule)
    return {"id": rule.id, **fields}


@router.delete(
    "/alerts/rules/{rule_id}",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if row is None:
        raise HTTPException(404, "rule not found")
    db.delete(row)
    db.commit()


@router.get("/alerts/events")
def list_alert_events(
    repo: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(AlertEvent).order_by(AlertEvent.fired_at.desc())
    if repo:
        repo = _validate_repo(repo)
        q = q.filter(AlertEvent.repo == repo)
    return {"events": [
        {
            "id": e.id, "rule_id": e.rule_id, "repo": e.repo,
            "metric": e.metric, "value": e.value, "prior_value": e.prior_value,
            "change_pct": e.change_pct, "channels_attempted": e.channels_attempted,
            "delivery_status": e.delivery_status, "detail": e.detail,
            "fired_at": e.fired_at.isoformat() if e.fired_at else None,
        } for e in q.limit(limit).all()
    ]}


@router.post("/alerts/evaluate", dependencies=[Depends(require_api_key)])
def trigger_alerts_evaluation(
    repo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Run rules NOW. Used both by the scheduler and by ops to trigger a
    one-off check after editing rules."""
    if repo is None:
        return {"results": evaluate_all_alerts(db)}
    repo = _validate_repo(repo)
    return {"results": {repo: evaluate_alerts_for_repo(db, repo)}}


# ── Repo listing ──────────────────────────────────────────────────────────
@router.get("/repos")
def list_repos():
    return {"repos": settings.github_repo_list}


# ── Sprint schedule (issue #14) ───────────────────────────────────────────
@router.get("/sprints")
def list_sprints():
    """Return a list of recent + upcoming sprints derived from
    `DORA_SPRINT_SCHEDULE` (`<anchor-iso-date>:<length-days>`).

    Each entry has start (inclusive) and end (exclusive, ISO Z) so callers
    can pass them straight to `/metrics/dora?start=...&end=...`. The window
    is the trailing 12 sprints + the current/next one, which keeps the
    dashboard dropdown small without losing retro-relevant history.
    """
    raw = (settings.sprint_schedule or "").strip()
    if not raw or ":" not in raw:
        return {"configured": False, "sprints": []}

    anchor_str, length_str = raw.split(":", 1)
    try:
        anchor = datetime.fromisoformat(anchor_str).replace(tzinfo=timezone.utc)
        length_days = int(length_str)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail="DORA_SPRINT_SCHEDULE malformed: expected '<iso-date>:<days>'",
        )
    if length_days < 1 or length_days > 60:
        raise HTTPException(
            status_code=500,
            detail="DORA_SPRINT_SCHEDULE length must be 1..60 days",
        )

    now = datetime.now(timezone.utc)
    elapsed_days = (now - anchor).days
    current_idx = elapsed_days // length_days  # 0-based; negative if anchor is in the future

    out = []
    # Trailing 12 + current + next 1 = 14 entries when fully populated.
    for i in range(max(0, current_idx - 12), current_idx + 2):
        start = anchor + timedelta(days=i * length_days)
        end = start + timedelta(days=length_days)
        out.append({
            "index": i + 1,  # 1-based for human-friendly labels
            "label": f"Sprint {i + 1}",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "is_current": i == current_idx,
        })

    return {
        "configured": True,
        "length_days": length_days,
        "anchor": anchor.isoformat().replace("+00:00", "Z"),
        "sprints": out,
    }


# ── Health probes ────────────────────────────────────────────────────────
@router.get("/health/live")
def health_live():
    """Liveness: process is up. Cheap, no I/O.

    K8s livenessProbe uses this. Failing → kubelet restarts the pod.
    """
    return {"status": "live", "version": "1.0.0"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    """Readiness: process is up *and* DB is reachable.

    K8s readinessProbe uses this. Failing → pod removed from the Service's
    endpoints (no traffic) but not restarted.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        logger.warning("readiness check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not reachable",
        )
    return {"status": "ready", "version": "1.0.0"}
