"""
OTLP/HTTP receiver for Claude Code telemetry (Plan A).

Accepts OTLP metric exports directly from the Claude Code CLI when configured with:
    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_METRICS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf  (or http/json)
    OTEL_EXPORTER_OTLP_ENDPOINT=https://<your-backend>/api/v1/otel
    OTEL_EXPORTER_OTLP_HEADERS=x-api-key=<DORA_API_KEY>

Maps known `claude_code.*` metric names into the existing claude_code_sessions
table, aggregated by (user_email, session_date).

Aggregation respects OTLP `aggregationTemporality`:
  AGGREGATION_TEMPORALITY_CUMULATIVE (2): the data point is the running total
    since process start. We track the maximum we have seen for each
    (user, date, metric_key) combination, so resending the same cumulative
    value is idempotent and the row reflects end-of-day totals.
  AGGREGATION_TEMPORALITY_DELTA (1): the data point is the increment since
    the last report. We add it to the row.

For more sophisticated routing, sampling, or fan-out to other observability
backends, run a real OTel Collector in front of this endpoint (Plan B) — see
docs/telemetry.md.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.security import require_api_key
from app.models.database import get_db
from app.models.events import ClaudeCodeSession, OtelCumulativeState

try:
    from google.protobuf.json_format import MessageToDict, Parse
    from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2
    _PROTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROTO_AVAILABLE = False


router = APIRouter(prefix="/api/v1/otel")
logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 4 * 1024 * 1024  # 4 MB cap

# Aggregation temporality enum from OTLP spec.
TEMPORALITY_DELTA = 1
TEMPORALITY_CUMULATIVE = 2

# `MessageToDict` (without preserving_proto_field_name=True and without
# `use_integers_for_enums=True`) serialises enum values as their string
# names — e.g. the int `1` becomes "AGGREGATION_TEMPORALITY_DELTA". We map
# both representations here so the receiver works regardless of the proto3
# JSON encoder settings on either side.
_TEMPORALITY_ALIASES = {
    "AGGREGATION_TEMPORALITY_UNSPECIFIED": 0,
    "AGGREGATION_TEMPORALITY_DELTA": TEMPORALITY_DELTA,
    "AGGREGATION_TEMPORALITY_CUMULATIVE": TEMPORALITY_CUMULATIVE,
}


def _coerce_temporality(raw) -> int:
    """Accept either the int form (1, 2) or the string form
    ('AGGREGATION_TEMPORALITY_*'). Unknown / missing → 0 (unspecified)."""
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        if raw in _TEMPORALITY_ALIASES:
            return _TEMPORALITY_ALIASES[raw]
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


# ── Metric routing ─────────────────────────────────────────────────────────
# Returns (db_field, value_increment, is_count_int) or None to ignore.

def _route(metric_name: str, attrs: dict, value: float):
    if metric_name == "claude_code.session.count":
        return ("num_sessions", value, True)
    if metric_name == "claude_code.lines_of_code.count":
        t = attrs.get("type")
        if t == "added":
            return ("lines_added", value, True)
        if t == "removed":
            return ("lines_removed", value, True)
        return None
    if metric_name == "claude_code.commit.count":
        return ("commits_created", value, True)
    if metric_name == "claude_code.pull_request.count":
        return ("prs_created", value, True)
    if metric_name == "claude_code.code_edit_tool.decision":
        d = attrs.get("decision")
        if d == "accept":
            return ("edit_accepted", value, True)
        if d == "reject":
            return ("edit_rejected", value, True)
        return None
    if metric_name == "claude_code.token.usage":
        t = attrs.get("type")
        if t == "input":
            return ("tokens_input", value, True)
        if t == "output":
            return ("tokens_output", value, True)
        return None
    if metric_name == "claude_code.cost.usage":
        return ("estimated_cost_cents", value * 100.0, False)
    return None


def _to_session_date(time_unix_nano) -> datetime:
    if time_unix_nano in (None, "", 0, "0"):
        return _today_utc_midnight()
    try:
        ns = int(time_unix_nano)
    except (TypeError, ValueError):
        return _today_utc_midnight()
    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _today_utc_midnight() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _attrs_to_dict(kvs: Iterable[dict]) -> dict:
    """Flatten OTLP KeyValue list (proto3-JSON form) into a plain dict."""
    out = {}
    for kv in kvs or []:
        key = kv.get("key")
        if not key:
            continue
        v = kv.get("value", {})
        if "stringValue" in v:
            out[key] = v["stringValue"]
        elif "intValue" in v:
            try:
                out[key] = int(v["intValue"])
            except (TypeError, ValueError):
                pass
        elif "doubleValue" in v:
            try:
                out[key] = float(v["doubleValue"])
            except (TypeError, ValueError):
                pass
        elif "boolValue" in v:
            out[key] = bool(v["boolValue"])
    return out


def _ingest_metrics_dict(payload: dict, db: Session) -> dict:
    accepted = 0
    skipped_no_user = 0
    rows_touched: set[tuple[str, datetime]] = set()

    for rm in payload.get("resourceMetrics", []) or []:
        resource_attrs = _attrs_to_dict((rm.get("resource") or {}).get("attributes", []))
        user_email = (
            resource_attrs.get("user.email")
            or resource_attrs.get("user.id")
            or resource_attrs.get("enduser.id")
        )
        primary_model = (
            resource_attrs.get("claude_code.model")
            or resource_attrs.get("model")
            or ""
        )

        if not user_email:
            skipped_no_user += 1
            continue

        for sm in rm.get("scopeMetrics", []) or []:
            for metric in sm.get("metrics", []) or []:
                name = metric.get("name", "")
                # Sum carries temporality; gauge has no temporality (treat as cumulative).
                sum_block = metric.get("sum") or {}
                gauge_block = metric.get("gauge") or {}
                if sum_block:
                    points = sum_block.get("dataPoints") or []
                    temporality = _coerce_temporality(
                        sum_block.get("aggregationTemporality")
                    )
                elif gauge_block:
                    points = gauge_block.get("dataPoints") or []
                    temporality = TEMPORALITY_CUMULATIVE
                else:
                    continue

                for dp in points:
                    point_attrs = _attrs_to_dict(dp.get("attributes", []))
                    raw = dp.get("asInt", dp.get("asDouble", 0))
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    routed = _route(name, point_attrs, value)
                    if routed is None:
                        continue
                    field, contribution, _is_int = routed
                    session_date = _to_session_date(dp.get("timeUnixNano"))
                    point_model = point_attrs.get("model") or primary_model

                    increment = _resolve_increment(
                        db=db,
                        user_email=user_email,
                        session_date=session_date,
                        metric_name=name,
                        attrs=point_attrs,
                        cumulative_value=contribution,
                        temporality=temporality,
                    )
                    if increment is None:
                        # cumulative regression (process restarted) — skip but don't error
                        continue

                    rows_touched.add((user_email, session_date))
                    _add_to_session(
                        db, user_email, session_date, field, increment,
                        primary_model, point_model,
                    )
                    accepted += 1

    db.commit()
    return {
        "accepted_points": accepted,
        "rows_touched": len(rows_touched),
        "skipped_no_user": skipped_no_user,
    }


def _resolve_increment(
    db: Session,
    user_email: str,
    session_date: datetime,
    metric_name: str,
    attrs: dict,
    cumulative_value: float,
    temporality: int,
) -> float | None:
    """
    Convert any data point into a delta to add to the row.

    For DELTA points: the value IS the delta — return it as-is.

    For CUMULATIVE points: subtract the last-seen cumulative for the same
    (user, date, metric, attrs) and persist the new high-water mark. Returns
    None if the new value is lower than what we've already seen (process
    restart with reset counter — we ignore it for the day rather than create
    negative rows).
    """
    if temporality == TEMPORALITY_DELTA:
        return cumulative_value

    # Cumulative path. Build a stable key over the metric + attribute fingerprint.
    attr_key = "|".join(f"{k}={v}" for k, v in sorted(attrs.items()))
    state_key = f"{metric_name}::{attr_key}"

    state = (
        db.query(OtelCumulativeState)
        .filter(
            OtelCumulativeState.user_email == user_email,
            OtelCumulativeState.session_date == session_date,
            OtelCumulativeState.metric_key == state_key,
        )
        .first()
    )

    if state is None:
        # First sighting today — the entire cumulative value is the delta to add.
        db.add(OtelCumulativeState(
            user_email=user_email,
            session_date=session_date,
            metric_key=state_key,
            last_value=cumulative_value,
        ))
        db.flush()
        return cumulative_value

    last = state.last_value or 0.0
    if cumulative_value < last:
        # Counter went backwards — process restart. Don't error; just resync
        # the high-water mark so future increments are correct, and skip this
        # point. (Slight underreport for the instant of restart; acceptable.)
        state.last_value = cumulative_value
        return None

    delta = cumulative_value - last
    state.last_value = cumulative_value
    return delta


def _add_to_session(
    db: Session,
    user_email: str,
    session_date: datetime,
    field: str,
    increment: float,
    primary_model: str,
    point_model: str | None,
):
    row = (
        db.query(ClaudeCodeSession)
        .filter(
            ClaudeCodeSession.user_email == user_email,
            ClaudeCodeSession.session_date == session_date,
        )
        .first()
    )
    if row is None:
        row = ClaudeCodeSession(user_email=user_email, session_date=session_date)
        db.add(row)
        db.flush()

    current = getattr(row, field, 0) or 0
    setattr(row, field, current + increment)

    if not row.model:
        row.model = point_model or primary_model or None


# ── HTTP entry point ───────────────────────────────────────────────────────
@router.post("/v1/metrics", dependencies=[Depends(require_api_key)])
async def receive_metrics(request: Request, db: Session = Depends(get_db)):
    """
    OTLP/HTTP metrics endpoint. Accepts:
      - application/x-protobuf  (OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf, default)
      - application/json        (OTEL_EXPORTER_OTLP_PROTOCOL=http/json)
    """
    if not _PROTO_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTLP support not installed (opentelemetry-proto missing).",
        )

    content_type = (request.headers.get("content-type") or "").lower().split(";")[0].strip()
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="OTLP body too large")

    try:
        if content_type == "application/x-protobuf":
            req = metrics_service_pb2.ExportMetricsServiceRequest()
            req.ParseFromString(raw)
            payload = MessageToDict(req, preserving_proto_field_name=False)
        elif content_type == "application/json":
            req = metrics_service_pb2.ExportMetricsServiceRequest()
            Parse(raw.decode("utf-8"), req)
            payload = MessageToDict(req, preserving_proto_field_name=False)
        else:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported content-type: {content_type}",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Malformed OTLP body: %s", e)
        raise HTTPException(status_code=400, detail=f"Malformed OTLP body: {e}")

    result = _ingest_metrics_dict(payload, db)
    return result


@router.post("/v1/logs", dependencies=[Depends(require_api_key)])
async def receive_logs():
    """Currently a no-op: logs are accepted to keep the CLI from buffering, but
    discarded. To persist Claude Code logs, run an OTel Collector (Plan B) and
    forward only what you need to a dedicated log store."""
    return {"status": "accepted_no_op"}
