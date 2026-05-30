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


# ── Sprint endpoint (issue #14) ───────────────────────────────────────────
def test_sprints_unconfigured_returns_empty(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.sprint_schedule", "")
    r = client.get("/api/v1/sprints")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["sprints"] == []


def test_sprints_returns_indexed_windows(client, monkeypatch):
    # 2-week sprints anchored well in the past so we always get a full window.
    monkeypatch.setattr(
        "app.config.settings.settings.sprint_schedule",
        "2024-01-01:14",
    )
    r = client.get("/api/v1/sprints")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["length_days"] == 14
    assert len(body["sprints"]) >= 2
    # exactly one entry should be flagged as current
    current = [s for s in body["sprints"] if s["is_current"]]
    assert len(current) == 1
    # windows are 14 days, contiguous, monotonically increasing
    for prev, nxt in zip(body["sprints"], body["sprints"][1:]):
        assert prev["end"] == nxt["start"]
        assert nxt["index"] == prev["index"] + 1


def test_sprints_malformed_schedule_returns_500(client, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings.sprint_schedule",
        "not-a-date:14",
    )
    r = client.get("/api/v1/sprints")
    assert r.status_code == 500


def test_retro_report_returns_markdown(client):
    r = client.get(
        "/api/v1/reports/retro",
        params={"days": 14, "sprint_label": "Sprint 3"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    body = r.text
    assert "# DORA Retro" in body
    assert "Sprint 3" in body


def test_retro_report_json_format(client):
    r = client.get("/api/v1/reports/retro", params={"days": 7, "format": "json"})
    assert r.status_code == 200
    body = r.json()
    assert "markdown" in body and body["markdown"].startswith("# DORA Retro")
    assert "summary" in body and "deployment_frequency" in body["summary"]


def test_level_history_empty_initially(client):
    r = client.get("/api/v1/metrics/level-history")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshots"] == []
    assert body["repo"] == "octo/repo"


def test_level_history_after_collect(client):
    # Bootstrap one week of snapshots
    r = client.post(
        "/api/v1/collect/level-snapshots?weeks=1",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    assert r.json()["rows_touched"] == 4

    r2 = client.get("/api/v1/metrics/level-history")
    body = r2.json()
    assert len(body["snapshots"]) == 1
    metrics = body["snapshots"][0]["metrics"]
    assert set(metrics.keys()) == {
        "deployment_frequency", "lead_time_for_changes",
        "change_failure_rate", "mean_time_to_recovery",
    }


def test_alert_rule_crud(client):
    # Empty initially
    r = client.get("/api/v1/alerts/rules")
    assert r.status_code == 200
    assert r.json()["rules"] == []

    # Create
    payload = {
        "repo": "octo/repo", "metric": "lead_time_for_changes",
        "operator": ">", "threshold": 24.0, "change_pct": 50.0,
        "channels": "slack",
    }
    r = client.post(
        "/api/v1/alerts/rules", json=payload,
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    rule_id = r.json()["id"]

    # Duplicate is 409
    r = client.post(
        "/api/v1/alerts/rules", json=payload,
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 409

    # List shows it
    r = client.get("/api/v1/alerts/rules")
    assert len(r.json()["rules"]) == 1

    # Bad metric → 400
    r = client.post(
        "/api/v1/alerts/rules",
        json={**payload, "metric": "made_up"},
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 400

    # Delete
    r = client.delete(f"/api/v1/alerts/rules/{rule_id}",
                      headers={"X-API-Key": "test-key"})
    assert r.status_code == 204
    r = client.get("/api/v1/alerts/rules")
    assert r.json()["rules"] == []


def test_alert_rule_create_requires_api_key(client):
    payload = {
        "repo": "octo/repo", "metric": "lead_time_for_changes",
        "operator": ">", "threshold": 24.0, "channels": "slack",
    }
    r = client.post("/api/v1/alerts/rules", json=payload)
    assert r.status_code == 401


def test_metrics_dora_accepts_explicit_range(client):
    r = client.get(
        "/api/v1/metrics/dora",
        params={"start": "2026-01-01T00:00:00Z", "end": "2026-01-15T00:00:00Z"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deployment_frequency"]["period"]["start"].startswith("2026-01-01")
    assert body["deployment_frequency"]["period"]["end"].startswith("2026-01-15")
