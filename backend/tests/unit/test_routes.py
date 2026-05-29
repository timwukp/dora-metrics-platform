"""Smoke-test the HTTP surface end-to-end against an in-memory app.

Focus areas:
  - Webhook replay: a duplicate `X-GitHub-Delivery` returns 200 no-op (so
    GitHub's retry storm does not spawn duplicate background work).
  - Health probes: /live answers without a DB; /ready does a SELECT 1.
  - Auth: mutating endpoints reject missing / wrong API keys.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch):
    """Construct a TestClient with the app's DB pointed at an in-memory SQLite.

    StaticPool keeps the same connection across requests so the schema we
    create persists for the test's lifetime.
    """
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

    # Patch the module-level DB handles before importing the app.
    monkeypatch.setattr("app.models.database.engine", engine)
    monkeypatch.setattr("app.models.database.SessionLocal", TestSession)

    # Avoid spinning up the scheduler in tests — it would attach to the
    # event loop and complain when the test client tears down.
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


def test_health_live_no_db(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "live"


def test_health_ready_succeeds_with_working_db(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_collect_endpoint_requires_api_key(client):
    r = client.post("/api/v1/collect/github")
    assert r.status_code == 401


def test_webhook_replay_protection(client):
    body = json.dumps({"repository": {"full_name": "octo/repo"}}).encode()
    sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-uuid-1",
        "Content-Type": "application/json",
    }
    r1 = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"

    r2 = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


def test_webhook_rejects_bad_signature(client):
    body = b"{}"
    r = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery-bad",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
