"""Weekly DORA-level snapshots (issue #16).

Persists one row per (repo, metric, week_start) into `dora_level_snapshots`.
Idempotent: re-running for the same week updates the existing row in place,
so the weekly scheduler can run more than once per week without producing
duplicate timeline entries.

Why a separate table instead of recomputing from history?
- Backfill is expensive (4 metrics × N weeks × M repos full SQL each).
- Threshold definitions can change. A snapshot freezes the level *as it
  was scored at the time*, which matters for "we went from Medium → High
  in 8 weeks" narratives.

Granularity is weekly because DORA bands have 4-tier resolution; daily
granularity would mostly show noise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.events import DoraLevelSnapshot
from app.services.dora_calculator import DoraCalculator

logger = logging.getLogger(__name__)

_METRICS = (
    ("deployment_frequency", "deploys_per_day"),
    ("lead_time_for_changes", "median_hours"),
    ("change_failure_rate", "cfr_pct"),
    ("mean_time_to_recovery", "median_hours"),
)


def _iso_week_start(dt: datetime) -> datetime:
    """Monday 00:00 UTC of the ISO week containing `dt`."""
    midnight = dt.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return midnight - timedelta(days=midnight.weekday())


def _value_for(summary: dict, metric: str, value_key: str):
    block = summary.get(metric) or {}
    v = block.get(value_key)
    # change_failure_rate may report cfr_pct as None when there are no deploys —
    # fall back to the combined rate so the chart still has a number.
    if v is None and metric == "change_failure_rate":
        v = block.get("combined_cfr_pct")
    return v, block.get("dora_level", "—"), block.get("sample_size") or 0


def snapshot_week(db: Session, repo: str, week_start: datetime) -> int:
    """Compute and persist one week's DORA snapshot for a repo. Returns
    number of rows touched (insert + update count)."""
    week_end = week_start + timedelta(days=7)
    summary = DoraCalculator(db, repo=repo).summary(week_start, week_end)

    touched = 0
    for metric, value_key in _METRICS:
        value, level, sample = _value_for(summary, metric, value_key)
        existing = (
            db.query(DoraLevelSnapshot)
            .filter(
                DoraLevelSnapshot.repo == repo,
                DoraLevelSnapshot.metric == metric,
                DoraLevelSnapshot.week_start == week_start,
            )
            .first()
        )
        if existing is None:
            db.add(DoraLevelSnapshot(
                repo=repo, metric=metric, week_start=week_start,
                level=level, value=value, sample_size=sample,
            ))
        else:
            existing.level = level
            existing.value = value
            existing.sample_size = sample
        touched += 1

    db.commit()
    return touched


def snapshot_recent_weeks(db: Session, repo: str, weeks: int = 1) -> int:
    """Snapshot the trailing `weeks` weeks (default: just the most recently
    completed week). The scheduler calls this with weeks=1; manual backfill
    can pass more."""
    now = datetime.now(timezone.utc)
    current_week_start = _iso_week_start(now)
    total = 0
    for i in range(weeks, 0, -1):
        ws = current_week_start - timedelta(days=7 * i)
        total += snapshot_week(db, repo, ws)
    return total


def list_snapshots(db: Session, repo: str, weeks: int = 26) -> list[dict]:
    """Return a chronological list of weekly snapshots for the dashboard
    timeline. `weeks` caps the look-back."""
    cutoff = _iso_week_start(datetime.now(timezone.utc)) - timedelta(days=7 * weeks)
    rows = (
        db.query(DoraLevelSnapshot)
        .filter(DoraLevelSnapshot.repo == repo,
                DoraLevelSnapshot.week_start >= cutoff)
        .order_by(DoraLevelSnapshot.week_start.asc(),
                  DoraLevelSnapshot.metric.asc())
        .all()
    )
    by_week: dict[str, dict] = {}
    for r in rows:
        key = r.week_start.isoformat().replace("+00:00", "Z")
        if key not in by_week:
            by_week[key] = {"week_start": key, "metrics": {}}
        by_week[key]["metrics"][r.metric] = {
            "level": r.level,
            "value": r.value,
            "sample_size": r.sample_size,
        }
    return list(by_week.values())
