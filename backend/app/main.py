"""FastAPI app entry point.

Highlights:

* **Scheduled jobs run under a Postgres advisory lock.** With multiple
  replicas in K8s, every replica's APScheduler ticks at the same cadence —
  without coordination they would all hit GitHub's API at once and double
  the work. `leader_lock(name)` is a context manager that returns True only
  to the current lock holder; everyone else skips the tick silently. The
  lock is session-scoped, so a crashed replica doesn't strand it.

* **Docs surface is feature-flagged.** `/docs` and `/openapi.json` are great
  for local development but expose every route to anyone who can reach the
  API. Production deployments set `DORA_ENABLE_DOCS=false` to disable them.

* **CORS without credentials.** We don't put session cookies on the wire —
  the frontend sends `X-API-Key` for mutating routes. Disabling
  `allow_credentials` lets us keep a strict origin allowlist without the
  browser's "credentials + wildcard" footgun.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.incident_webhooks import router as incident_webhooks_router
from app.api.otel_receiver import router as otel_router
from app.api.routes import router
from app.collectors.claude_code_collector import ClaudeCodeCollector
from app.collectors.github_collector import GitHubCollector
from app.config.settings import settings
from app.models.database import Base, SessionLocal, engine
from app.services.leader import leader_lock

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scheduled_github_collection():
    if not settings.github_token or not settings.github_repo_list:
        return
    with leader_lock("github_collection") as is_leader:
        if not is_leader:
            return
        db = SessionLocal()
        try:
            collector = GitHubCollector()
            for repo in settings.github_repo_list:
                await collector.collect_all(db, repo)
                await collector.collect_reviews(db, repo)
            logger.info("GitHub collection completed")
        except Exception:
            logger.exception("GitHub collection failed")
        finally:
            db.close()


async def scheduled_level_snapshot():
    """Weekly DORA-level snapshots (issue #16). Runs daily under the leader
    lock so it self-heals if a previous run was missed; the writer is
    idempotent per (repo, metric, week_start)."""
    if not settings.github_repo_list:
        return
    with leader_lock("level_snapshot") as is_leader:
        if not is_leader:
            return
        from app.services.level_history import snapshot_recent_weeks
        db = SessionLocal()
        try:
            for repo in settings.github_repo_list:
                snapshot_recent_weeks(db, repo, weeks=1)
            logger.info("Level snapshot completed")
        except Exception:
            logger.exception("Level snapshot failed")
        finally:
            db.close()


async def scheduled_alert_evaluation():
    """Daily DORA alert evaluation (issue #15)."""
    with leader_lock("alert_evaluation") as is_leader:
        if not is_leader:
            return
        from app.services.alerts import evaluate_all
        db = SessionLocal()
        try:
            evaluate_all(db)
        except Exception:
            logger.exception("Alert evaluation failed")
        finally:
            db.close()


async def scheduled_claude_code_collection():
    if not settings.claude_code_admin_key:
        return
    with leader_lock("claude_code_collection") as is_leader:
        if not is_leader:
            return
        db = SessionLocal()
        try:
            collector = ClaudeCodeCollector()
            start = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            await collector.collect(db, start)
            logger.info("Claude Code collection completed")
        except Exception:
            logger.exception("Claude Code collection failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler.add_job(
        scheduled_github_collection, "interval",
        minutes=settings.poll_interval_minutes, id="github_collection",
    )
    scheduler.add_job(
        scheduled_claude_code_collection, "interval",
        minutes=60, id="claude_code_collection",
    )
    scheduler.add_job(
        scheduled_level_snapshot, "interval",
        hours=24, id="level_snapshot",
    )
    scheduler.add_job(
        scheduled_alert_evaluation, "interval",
        hours=24, id="alert_evaluation",
    )
    scheduler.start()
    asyncio.create_task(scheduled_github_collection())
    asyncio.create_task(scheduled_claude_code_collection())
    asyncio.create_task(scheduled_level_snapshot())
    yield
    scheduler.shutdown()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """OWASP-recommended response headers."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # Strict CSP for the JSON API surface; frontend serves its own.
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        # HSTS only meaningful when behind TLS — safe to send unconditionally.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


_docs_url = "/docs" if settings.enable_docs else None
_openapi_url = "/openapi.json" if settings.enable_docs else None

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=None,
    openapi_url=_openapi_url,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,  # validated: no wildcard
    # We do not use cookies — the API is keyed via X-API-Key. Disabling
    # credentials avoids the browser footgun where an origin allowlist plus
    # credentials lets a misconfigured wildcard leak responses.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type", "X-API-Key", "X-Hub-Signature-256", "X-GitHub-Event",
        "X-GitHub-Delivery",
        # OTLP/HTTP exporters send these:
        "User-Agent", "Accept",
    ],
    max_age=600,
)

app.include_router(router)
app.include_router(otel_router)
app.include_router(incident_webhooks_router)
