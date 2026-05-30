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
from app.models.database import SessionLocal, engine
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


def _warn_if_fargate() -> None:
    """If we're running on EKS Fargate, NetworkPolicy is silently no-op
    (Fargate uses its own datapath and does not run the VPC-CNI policy
    enforcement). Log a loud WARNING so operators don't assume the
    `default-deny-all` NetworkPolicy is actually doing anything.

    The signal is the node name: Fargate-scheduled pods always run on
    nodes named `fargate-…`. We get that via the downward API as
    K8S_NODE_NAME (set in backend.yaml).
    """
    import os
    node = os.environ.get("K8S_NODE_NAME", "")
    if node.startswith("fargate-"):
        logger.warning(
            "DETECTED EKS FARGATE NODE (%s): NetworkPolicy is NOT enforced "
            "on Fargate. The shipped default-deny-all NetworkPolicy is a "
            "silent no-op. Use Security Groups for Pods (SGP) or replace "
            "Fargate with a managed node group. See "
            "docs/EKS-DEPLOY.md#fargate-clusters",
            node,
        )


def _check_or_apply_migrations() -> None:
    """Schema is owned by Alembic. If `DORA_AUTO_MIGRATE` is true we run
    `alembic upgrade head` here (convenient for trial mode). Otherwise we
    just warn — production should run the dedicated migrate Job before the
    Deployment becomes ready."""
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    import os

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location",
                        os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    if engine.url.drivername.startswith("sqlite"):
        # Unit tests use Base.metadata.create_all on an in-memory SQLite
        # engine; Alembic isn't in that path. Production runs Postgres.
        logger.debug("SQLite engine detected; skipping Alembic revision check")
        return

    if os.environ.get("DORA_AUTO_MIGRATE", "").lower() in ("1", "true", "yes"):
        logger.info("DORA_AUTO_MIGRATE=true → running alembic upgrade head")
        command.upgrade(cfg, "head")
        return

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        rev = ctx.get_current_revision()
    if rev is None:
        logger.error(
            "Database has no Alembic revision applied. Run "
            "`alembic upgrade head` (or set DORA_AUTO_MIGRATE=true) before "
            "starting the backend.")
        raise RuntimeError("schema not migrated")
    logger.info("Alembic head detected at revision %s", rev)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_if_fargate()
    _check_or_apply_migrations()
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
