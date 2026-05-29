"""Verify the OTLP cumulative-vs-delta logic does not double-count or
under-count cost — the original implementation used max() on every field
which left cost stuck at the first reported value.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.api.otel_receiver import _ingest_metrics_dict
from app.models.events import ClaudeCodeSession, OtelCumulativeState


def _payload(sum_block_overrides: dict, value: float, ts_ns: int):
    """Build the minimum OTLP-style dict our ingest path expects."""
    sum_block = {
        "aggregationTemporality": 2,  # cumulative
        "isMonotonic": True,
        "dataPoints": [
            {
                "asDouble": value,
                "timeUnixNano": str(ts_ns),
                "attributes": [],
            }
        ],
    }
    sum_block.update(sum_block_overrides)
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "user.email", "value": {"stringValue": "tim@example.com"}}
                    ]
                },
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "claude_code.cost.usage",
                                "sum": sum_block,
                            }
                        ]
                    }
                ],
            }
        ]
    }


def _ts(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1e9)


def test_cumulative_cost_accumulates_via_delta(db_session):
    ts = _ts(2026, 5, 28)
    _ingest_metrics_dict(_payload({}, value=0.5, ts_ns=ts), db_session)
    _ingest_metrics_dict(_payload({}, value=1.5, ts_ns=ts), db_session)
    _ingest_metrics_dict(_payload({}, value=2.5, ts_ns=ts), db_session)

    row = db_session.query(ClaudeCodeSession).first()
    # 2.5 cumulative → cost in cents = 250.0 (full delta is 2.5 from 0)
    assert row is not None
    assert row.estimated_cost_cents == 250.0


def test_cumulative_counter_regression_does_not_underflow(db_session):
    """If the CLI process restarts and sends a *lower* cumulative value, we
    must not record a negative delta."""
    ts = _ts(2026, 5, 28)
    _ingest_metrics_dict(_payload({}, value=10.0, ts_ns=ts), db_session)
    _ingest_metrics_dict(_payload({}, value=2.0, ts_ns=ts), db_session)  # restart

    row = db_session.query(ClaudeCodeSession).first()
    assert row.estimated_cost_cents == 1000.0  # the regression point is dropped

    # State should resync so future increments are correct. Cost is stored
    # in cents (the routing multiplies by 100) so the high-water mark is
    # 200.0 cents == $2.0.
    state = db_session.query(OtelCumulativeState).first()
    assert state.last_value == 200.0


def test_delta_temporality_adds_directly(db_session):
    ts = _ts(2026, 5, 28)
    payload = _payload({"aggregationTemporality": 1}, value=0.7, ts_ns=ts)
    _ingest_metrics_dict(payload, db_session)
    _ingest_metrics_dict(payload, db_session)

    row = db_session.query(ClaudeCodeSession).first()
    # delta * 100 (cents) summed twice
    assert round(row.estimated_cost_cents, 2) == 140.0


def test_temporality_accepts_string_enum(db_session):
    """`MessageToDict` serialises the temporality as
    'AGGREGATION_TEMPORALITY_DELTA' rather than the int 1. The receiver
    must accept both — production traffic from the Claude Code CLI uses
    the string form, and `int('AGGREGATION_TEMPORALITY_DELTA')` blew up
    every metrics POST until this was fixed.
    """
    ts = _ts(2026, 5, 28)
    payload = _payload(
        {"aggregationTemporality": "AGGREGATION_TEMPORALITY_DELTA"},
        value=1.5,
        ts_ns=ts,
    )
    _ingest_metrics_dict(payload, db_session)

    row = db_session.query(ClaudeCodeSession).first()
    assert row is not None
    assert round(row.estimated_cost_cents, 2) == 150.0
