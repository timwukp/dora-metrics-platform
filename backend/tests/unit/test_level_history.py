"""Weekly DORA-level snapshot service (issue #16)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.events import DoraLevelSnapshot
from app.services.level_history import (
    _iso_week_start, list_snapshots, snapshot_week,
)


def _monday_two_weeks_ago() -> datetime:
    return _iso_week_start(datetime.now(timezone.utc) - timedelta(days=14))


def test_snapshot_week_writes_one_row_per_metric(db_session):
    ws = _monday_two_weeks_ago()
    touched = snapshot_week(db_session, "octo/repo", ws)
    rows = db_session.query(DoraLevelSnapshot).filter(
        DoraLevelSnapshot.repo == "octo/repo",
        DoraLevelSnapshot.week_start == ws,
    ).all()
    assert touched == 4
    assert len(rows) == 4
    assert {r.metric for r in rows} == {
        "deployment_frequency", "lead_time_for_changes",
        "change_failure_rate", "mean_time_to_recovery",
    }


def test_snapshot_week_is_idempotent(db_session):
    ws = _monday_two_weeks_ago()
    snapshot_week(db_session, "octo/repo", ws)
    snapshot_week(db_session, "octo/repo", ws)  # second pass
    rows = db_session.query(DoraLevelSnapshot).filter(
        DoraLevelSnapshot.repo == "octo/repo",
        DoraLevelSnapshot.week_start == ws,
    ).all()
    assert len(rows) == 4  # not 8


def test_list_snapshots_groups_by_week(db_session):
    ws1 = _monday_two_weeks_ago()
    ws2 = ws1 + timedelta(days=7)
    snapshot_week(db_session, "octo/repo", ws1)
    snapshot_week(db_session, "octo/repo", ws2)

    out = list_snapshots(db_session, "octo/repo", weeks=10)
    assert len(out) == 2
    assert out[0]["week_start"] < out[1]["week_start"]
    for entry in out:
        assert "deployment_frequency" in entry["metrics"]
        assert "level" in entry["metrics"]["deployment_frequency"]


def test_list_snapshots_respects_weeks_window(db_session):
    # Insert a snapshot far in the past — should be filtered out by the
    # 1-week look-back.
    ws_old = _iso_week_start(datetime.now(timezone.utc) - timedelta(days=120))
    snapshot_week(db_session, "octo/repo", ws_old)
    out = list_snapshots(db_session, "octo/repo", weeks=1)
    assert out == []
