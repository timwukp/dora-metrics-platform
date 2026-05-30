"""DORA regression alerts (issue #15)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.events import AlertEvent, AlertRule
from app.services import alerts as alerts_mod


def _summary(metric_block: str, value_key: str, value):
    """Build a minimal calculator-shaped summary just for the rule under test."""
    return {metric_block: {value_key: value}}


def _make_rule(db_session, **kwargs):
    defaults = dict(
        repo="octo/repo", metric="lead_time_for_changes",
        operator=">", threshold=10.0, change_pct=None,
        channels="slack", enabled=True,
    )
    defaults.update(kwargs)
    rule = AlertRule(**defaults)
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def test_rule_fires_when_threshold_breached(db_session):
    _make_rule(db_session)
    current = _summary("lead_time_for_changes", "median_hours", 24.0)
    prior = _summary("lead_time_for_changes", "median_hours", 8.0)

    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert len(fired) == 1
    assert fired[0]["delivery_status"] == "stub"  # alerts_enabled=False default
    events = db_session.query(AlertEvent).all()
    assert len(events) == 1
    assert events[0].value == 24.0


def test_rule_does_not_fire_below_threshold(db_session):
    _make_rule(db_session)
    current = _summary("lead_time_for_changes", "median_hours", 4.0)
    prior = _summary("lead_time_for_changes", "median_hours", 3.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert fired == []


def test_change_pct_gate_suppresses_first_breach(db_session):
    _make_rule(db_session, threshold=10.0, change_pct=50.0)
    # Threshold breached, but only +20% growth — below 50% gate.
    current = _summary("lead_time_for_changes", "median_hours", 12.0)
    prior = _summary("lead_time_for_changes", "median_hours", 10.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert fired == []


def test_change_pct_gate_fires_on_large_jump(db_session):
    _make_rule(db_session, threshold=10.0, change_pct=50.0)
    current = _summary("lead_time_for_changes", "median_hours", 25.0)
    prior = _summary("lead_time_for_changes", "median_hours", 10.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert len(fired) == 1


def test_dedup_within_seven_days(db_session):
    rule = _make_rule(db_session)
    # First evaluation fires; second within window is deduped.
    current = _summary("lead_time_for_changes", "median_hours", 50.0)
    prior = _summary("lead_time_for_changes", "median_hours", 5.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior, current, prior]):
        fired1 = alerts_mod.evaluate_repo(db_session, "octo/repo")
        fired2 = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert len(fired1) == 1
    assert fired2[0].get("skipped") == "deduped"
    # Only one event row.
    assert db_session.query(AlertEvent).filter(AlertEvent.rule_id == rule.id).count() == 1


def test_dedup_window_expires(db_session):
    rule = _make_rule(db_session)
    # Insert a stale event 8 days ago; new fire should still go through.
    stale = AlertEvent(
        rule_id=rule.id, repo=rule.repo, metric=rule.metric,
        value=99, fired_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db_session.add(stale)
    db_session.commit()

    current = _summary("lead_time_for_changes", "median_hours", 50.0)
    prior = _summary("lead_time_for_changes", "median_hours", 5.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert len(fired) == 1


def test_disabled_rule_does_not_fire(db_session):
    _make_rule(db_session, enabled=False)
    current = _summary("lead_time_for_changes", "median_hours", 99.0)
    prior = _summary("lead_time_for_changes", "median_hours", 1.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert fired == []


def test_slack_dispatch_when_enabled(db_session, monkeypatch):
    _make_rule(db_session)
    monkeypatch.setattr(alerts_mod.settings, "alerts_enabled", True)
    monkeypatch.setattr(alerts_mod.settings, "alerts_slack_webhook",
                        "https://hooks.slack.example/T/B/X")

    posted = {}

    def fake_post(url, json, timeout):  # noqa: A002
        posted["url"] = url
        posted["json"] = json
        class _R:
            status_code = 200
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    current = _summary("lead_time_for_changes", "median_hours", 50.0)
    prior = _summary("lead_time_for_changes", "median_hours", 5.0)
    with patch.object(alerts_mod.DoraCalculator, "summary",
                      side_effect=[current, prior]):
        fired = alerts_mod.evaluate_repo(db_session, "octo/repo")
    assert len(fired) == 1
    assert fired[0]["delivery_status"] == "ok"
    assert posted["url"].endswith("/X")
    assert "DORA alert" in posted["json"]["text"]
