"""PagerDuty / OpsGenie webhook receivers (issue #17)."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine)

    from app.models.database import Base
    Base.metadata.create_all(engine)

    monkeypatch.setattr("app.models.database.engine", engine)
    monkeypatch.setattr("app.models.database.SessionLocal", TestSession)
    monkeypatch.setattr(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler.start",
        lambda self: None,
    )
    monkeypatch.setattr(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler.shutdown",
        lambda self, wait=True: None,
    )
    monkeypatch.setattr(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler.add_job",
        lambda *a, **kw: None,
    )

    from app.main import app
    from app.models.database import get_db

    def _override_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ── PagerDuty ─────────────────────────────────────────────────────────────
def _pd_payload(event_type="incident.triggered", incident_id="PD-123",
                resolved_at=None):
    return {
        "event": {
            "id": "ev-1",
            "event_type": event_type,
            "occurred_at": "2026-05-29T10:00:00Z",
            "data": {
                "id": incident_id,
                "title": "API latency high",
                "priority": {"summary": "P1"},
                "created_at": "2026-05-29T09:55:00Z",
                "resolved_at": resolved_at,
            },
        }
    }


def test_pagerduty_creates_incident_without_secret(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.pagerduty_webhook_secret", None,
    )
    body = json.dumps(_pd_payload()).encode()
    r = client.post(
        "/api/v1/webhooks/pagerduty", content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "created"


def test_pagerduty_signature_required_when_secret_set(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.pagerduty_webhook_secret", "topsecret",
    )
    body = json.dumps(_pd_payload()).encode()
    r = client.post(
        "/api/v1/webhooks/pagerduty", content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401

    sig = "v1=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/v1/webhooks/pagerduty", content=body,
        headers={
            "Content-Type": "application/json",
            "X-PagerDuty-Signature": sig,
        },
    )
    assert r.status_code == 200


def test_pagerduty_resolution_updates_existing(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.pagerduty_webhook_secret", None,
    )
    # First call creates
    r = client.post(
        "/api/v1/webhooks/pagerduty",
        content=json.dumps(_pd_payload()).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.json()["status"] == "created"

    # Second call resolves
    body = json.dumps(_pd_payload(
        event_type="incident.resolved",
        resolved_at="2026-05-29T10:30:00Z",
    )).encode()
    r = client.post(
        "/api/v1/webhooks/pagerduty", content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.json()["status"] == "resolved"


def test_pagerduty_replay_protection(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.pagerduty_webhook_secret", None,
    )
    body = json.dumps(_pd_payload()).encode()
    r1 = client.post("/api/v1/webhooks/pagerduty", content=body,
                     headers={"Content-Type": "application/json"})
    r2 = client.post("/api/v1/webhooks/pagerduty", content=body,
                     headers={"Content-Type": "application/json"})
    assert r1.json()["status"] == "created"
    assert r2.json()["status"] == "duplicate"


# ── OpsGenie ──────────────────────────────────────────────────────────────
def _og_payload(action="Create", alert_id="og-42", updated_at=None):
    return {
        "action": action,
        "alert": {
            "alertId": alert_id,
            "tinyId": "T7",
            "message": "DB connections exhausted",
            "priority": "P2",
            "createdAt": "2026-05-29T09:00:00Z",
            "updatedAt": updated_at,
        },
    }


def test_opsgenie_creates_and_resolves(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.opsgenie_webhook_secret", "tok",
    )
    headers = {"Content-Type": "application/json", "X-OpsGenie-Token": "tok"}

    r = client.post(
        "/api/v1/webhooks/opsgenie",
        content=json.dumps(_og_payload()).encode(),
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "created"

    r2 = client.post(
        "/api/v1/webhooks/opsgenie",
        content=json.dumps(_og_payload(
            action="Close", updated_at="2026-05-29T09:45:00Z",
        )).encode(),
        headers=headers,
    )
    assert r2.json()["status"] == "resolved"


def test_opsgenie_token_mismatch_rejected(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.opsgenie_webhook_secret", "tok",
    )
    r = client.post(
        "/api/v1/webhooks/opsgenie",
        content=json.dumps(_og_payload()).encode(),
        headers={"Content-Type": "application/json", "X-OpsGenie-Token": "wrong"},
    )
    assert r.status_code == 401


def test_opsgenie_malformed_json(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.opsgenie_webhook_secret", None,
    )
    r = client.post(
        "/api/v1/webhooks/opsgenie",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
