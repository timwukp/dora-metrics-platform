"""PagerDuty / OpsGenie webhook receivers (issue #17).

Both providers POST JSON payloads describing incident lifecycle events
(triggered, acknowledged, resolved). We extract the timestamps and persist
them as `Incident` rows so MTTR is computed from real signals instead of
hotfix-PR proxies.

Trial-mode caveats:
- HMAC verification is enforced when the corresponding secret is
  configured. With no secret configured, we accept (useful for local
  smoke tests) and log a warning so operators notice.
- Service → repo mapping is intentionally minimal: we use
  `DORA_INCIDENT_DEFAULT_REPO`, falling back to the first configured repo.
  Production would map by service ID.
- Replay protection comes from the `(source, external_id)` unique
  constraint on `incidents`. A duplicate trigger event is a 200 no-op so
  the provider stops retrying.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fastapi import Depends
from app.config.settings import settings
from app.models.database import get_db
from app.models.events import Incident

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks")

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB cap


def _resolve_repo() -> str:
    if settings.incident_default_repo:
        return settings.incident_default_repo
    if settings.github_repo_list:
        return settings.github_repo_list[0]
    raise HTTPException(
        status_code=503,
        detail="No repos configured to attribute incidents to.",
    )


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # Tolerate both ISO with `Z` suffix and with explicit offset.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        return None


# ── PagerDuty ─────────────────────────────────────────────────────────────
def _verify_pagerduty(body: bytes, signature_header: Optional[str]) -> bool:
    secret = settings.pagerduty_webhook_secret
    if not secret:
        logger.warning("pagerduty_webhook_secret unset — accepting unsigned webhook")
        return True
    if not signature_header:
        return False
    # PagerDuty sends `v1=hex,v1=hex,...` (rotating secrets). Match any.
    expected = "v1=" + hmac.new(
        secret.encode(), body, hashlib.sha256,
    ).hexdigest()
    candidates = [c.strip() for c in signature_header.split(",")]
    return any(hmac.compare_digest(expected, c) for c in candidates)


@router.post("/pagerduty")
async def receive_pagerduty(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "body too large")
    if not _verify_pagerduty(raw, request.headers.get("x-pagerduty-signature")):
        raise HTTPException(401, "invalid PagerDuty signature")

    import json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "malformed JSON")

    # PagerDuty V3 webhook envelope: { "event": { "event_type": ..., "data": {...} } }
    event = payload.get("event") or {}
    data = event.get("data") or {}
    event_type = event.get("event_type") or ""

    external_id = data.get("id") or event.get("id")
    if not external_id:
        raise HTTPException(400, "missing incident id")

    title = data.get("title") or data.get("summary") or "PagerDuty incident"
    severity = (data.get("priority") or {}).get("summary") or data.get("urgency") or "high"
    started_at = _parse_iso(data.get("created_at") or event.get("occurred_at")) or datetime.now(timezone.utc)
    resolved_at = None
    if event_type.endswith("resolved"):
        resolved_at = _parse_iso(data.get("resolved_at") or event.get("occurred_at"))

    return _upsert_incident(
        db=db, source="pagerduty", external_id=str(external_id),
        title=title, severity=severity,
        started_at=started_at, resolved_at=resolved_at,
    )


# ── OpsGenie ──────────────────────────────────────────────────────────────
def _verify_opsgenie(token_header: Optional[str]) -> bool:
    secret = settings.opsgenie_webhook_secret
    if not secret:
        logger.warning("opsgenie_webhook_secret unset — accepting unauthenticated webhook")
        return True
    if not token_header:
        return False
    return hmac.compare_digest(secret, token_header)


@router.post("/opsgenie")
async def receive_opsgenie(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "body too large")
    if not _verify_opsgenie(request.headers.get("x-opsgenie-token")):
        raise HTTPException(401, "invalid OpsGenie token")

    import json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "malformed JSON")

    action = (payload.get("action") or "").lower()
    alert = payload.get("alert") or {}
    external_id = alert.get("alertId") or alert.get("tinyId")
    if not external_id:
        raise HTTPException(400, "missing alert id")

    title = alert.get("message") or "OpsGenie alert"
    severity = (alert.get("priority") or "P3").lower()
    started_at = _parse_iso(alert.get("createdAt")) or datetime.now(timezone.utc)
    resolved_at = None
    if action in {"close", "closealert", "resolve", "resolved"}:
        resolved_at = _parse_iso(alert.get("updatedAt")) or datetime.now(timezone.utc)

    return _upsert_incident(
        db=db, source="opsgenie", external_id=str(external_id),
        title=title, severity=severity,
        started_at=started_at, resolved_at=resolved_at,
    )


# ── Shared upsert ─────────────────────────────────────────────────────────
def _upsert_incident(
    *, db: Session, source: str, external_id: str,
    title: str, severity: str,
    started_at: datetime, resolved_at: Optional[datetime],
) -> dict:
    row = (
        db.query(Incident)
        .filter(Incident.source == source, Incident.external_id == external_id)
        .first()
    )
    if row is None:
        row = Incident(
            repo=_resolve_repo(),
            source=source, external_id=external_id,
            title=title, severity=severity,
            started_at=started_at, resolved_at=resolved_at,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Lost a race with another worker — treat as duplicate.
            db.rollback()
            return {"status": "duplicate"}
        return {"status": "created", "id": row.id}

    # Existing incident — only update resolution if we have one and it
    # wasn't recorded yet. Don't allow re-opening (would corrupt MTTR).
    if resolved_at and row.resolved_at is None:
        row.resolved_at = resolved_at
        db.commit()
        return {"status": "resolved", "id": row.id}
    return {"status": "duplicate", "id": row.id}
