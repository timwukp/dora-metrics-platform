"""DORA regression alerts (issue #15).

Two responsibilities:

1. **Evaluation** — given a `DoraCalculator.summary()` for a window and the
   prior equal-length window, decide which configured `AlertRule`s should
   fire. A rule fires when its threshold is breached AND (if configured)
   the metric has changed by `change_pct` vs the prior window.

2. **Dispatch** — write an `AlertEvent` row regardless of channel state
   (so we have an audit trail). Only attempt the network calls when the
   relevant channel is configured AND `alerts_enabled` is true. Failures
   never raise — they're recorded on the event row so a misconfigured
   webhook can't take the scheduler down.

Stub mode (default): channel adapters log the would-be payload at INFO
and mark the event `delivery_status='stub'`. Tests rely on this path so
they can exercise the dispatch logic without a network.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.events import AlertEvent, AlertRule
from app.services.dora_calculator import DoraCalculator

logger = logging.getLogger(__name__)

DEDUP_WINDOW_DAYS = 7

# Maps a metric name to (block_key, value_key, higher_is_better).
_METRIC_PATHS = {
    "deployment_frequency": ("deployment_frequency", "deploys_per_day", True),
    "lead_time_for_changes": ("lead_time_for_changes", "median_hours", False),
    "change_failure_rate": ("change_failure_rate", "cfr_pct", False),
    "mean_time_to_recovery": ("mean_time_to_recovery", "median_hours", False),
}


def _extract(summary: dict, metric: str):
    block_key, value_key, _ = _METRIC_PATHS[metric]
    block = (summary or {}).get(block_key) or {}
    return block.get(value_key)


def _ops_match(value, op: str, threshold: float) -> bool:
    if value is None:
        return False
    return {
        ">":  value > threshold,
        "<":  value < threshold,
        ">=": value >= threshold,
        "<=": value <= threshold,
    }.get(op, False)


def _pct_change(current, prior):
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior) * 100.0


# ── Channel adapters ──────────────────────────────────────────────────────
def _send_slack(message: dict) -> str:
    """Returns delivery_status: 'ok' | 'failed' | 'stub'."""
    if not settings.alerts_slack_webhook:
        logger.info("alerts: slack webhook unset — stub send: %s", message["text"])
        return "stub"
    try:
        import httpx
        r = httpx.post(settings.alerts_slack_webhook, json=message, timeout=5.0)
        if 200 <= r.status_code < 300:
            return "ok"
        logger.warning("slack alert failed: HTTP %s", r.status_code)
        return "failed"
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("slack alert dispatch raised: %s", e)
        return "failed"


def _send_email(message: dict) -> str:
    if not settings.alerts_email_to or not settings.alerts_smtp:
        logger.info("alerts: email unconfigured — stub send: %s", message["subject"])
        return "stub"
    # Real SMTP delivery is intentionally not implemented in trial mode.
    # The hook is here so a future PR can swap stub for `smtplib.SMTP(...)`
    # without touching the evaluator.
    logger.info("alerts: email channel configured but trial-mode stub: %s",
                message["subject"])
    return "stub"


_CHANNEL_DISPATCHERS = {
    "slack": _send_slack,
    "email": _send_email,
}


# ── Evaluation ────────────────────────────────────────────────────────────
def _format_message(rule: AlertRule, current, prior, change_pct) -> dict:
    direction = "up" if (change_pct or 0) > 0 else "down"
    text = (
        f"DORA alert: {rule.repo} {rule.metric} = {current} "
        f"(threshold {rule.operator} {rule.threshold}"
        + (f", change {change_pct:+.1f}% {direction} vs prior window" if change_pct is not None else "")
        + ")"
    )
    return {
        "text": text,
        "subject": f"[DORA] {rule.repo} {rule.metric} alert",
    }


def _recent_event_exists(db: Session, rule_id: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEDUP_WINDOW_DAYS)
    return (
        db.query(AlertEvent)
        .filter(AlertEvent.rule_id == rule_id, AlertEvent.fired_at >= cutoff)
        .first()
        is not None
    )


def evaluate_repo(db: Session, repo: str, *, days: int = 30) -> list[dict]:
    """Run all enabled rules for one repo against current vs prior window.
    Records AlertEvent rows for fires; returns a serialisable summary used
    by tests and the API."""
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    prior_start = current_start - timedelta(days=days)

    calc = DoraCalculator(db, repo=repo)
    current = calc.summary(current_start, now)
    prior = calc.summary(prior_start, current_start)

    rules = (
        db.query(AlertRule)
        .filter(AlertRule.repo == repo, AlertRule.enabled.is_(True))
        .all()
    )

    fired: list[dict] = []
    for rule in rules:
        if rule.metric not in _METRIC_PATHS:
            continue
        cur = _extract(current, rule.metric)
        prv = _extract(prior, rule.metric)
        if not _ops_match(cur, rule.operator, rule.threshold):
            continue
        change = _pct_change(cur, prv)
        if rule.change_pct is not None:
            if change is None or abs(change) < abs(rule.change_pct):
                continue

        if _recent_event_exists(db, rule.id):
            fired.append({"rule_id": rule.id, "skipped": "deduped"})
            continue

        message = _format_message(rule, cur, prv, change)
        channels = [c.strip() for c in (rule.channels or "").split(",") if c.strip()]

        statuses: list[tuple[str, str]] = []
        if settings.alerts_enabled:
            for ch in channels:
                disp = _CHANNEL_DISPATCHERS.get(ch)
                statuses.append((ch, disp(message) if disp else "failed"))
        else:
            for ch in channels:
                statuses.append((ch, "stub"))

        worst = "ok"
        if any(s == "failed" for _, s in statuses):
            worst = "failed"
        elif all(s == "stub" for _, s in statuses) or not statuses:
            worst = "stub"

        event = AlertEvent(
            rule_id=rule.id, repo=repo, metric=rule.metric,
            value=cur, prior_value=prv, change_pct=change,
            channels_attempted=",".join(channels),
            delivery_status=worst,
            detail=message["text"],
        )
        db.add(event)
        db.flush()
        fired.append({
            "rule_id": rule.id, "metric": rule.metric, "value": cur,
            "prior": prv, "change_pct": change, "delivery_status": worst,
        })

    db.commit()
    return fired


def evaluate_all(db: Session) -> dict:
    """Iterate over all distinct repos that have enabled rules."""
    repos = [
        row[0] for row in db.query(AlertRule.repo)
        .filter(AlertRule.enabled.is_(True)).distinct()
    ]
    out = {}
    for repo in repos:
        out[repo] = evaluate_repo(db, repo)
    return out
