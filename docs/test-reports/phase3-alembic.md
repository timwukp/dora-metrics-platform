# Phase 3 Test Report: Alembic migrations

**Date:** 2026-05-30
**Resolves:** #31

## Scope

Replace `Base.metadata.create_all(bind=engine)` at startup with proper
Alembic migrations:

- Initial schema migration covering all 12 tables
- Lifespan checks Alembic head; refuses to start if DB is unmigrated (or
  applies migrations when `DORA_AUTO_MIGRATE=true`, used in trial mode)
- New `infra/k8s/base/migrate-job.yaml` runs `alembic upgrade head` before
  the backend Deployment becomes ready
- Dockerfile now COPYs `backend/alembic/` and `backend/alembic.ini` into the
  image so both the migrate Job and the auto-migrate fallback work

## Tables in initial migration

12 application tables + `alembic_version`:

```
alembic_version
alert_events
alert_rules
claude_code_sessions
commits
deployments
dora_level_snapshots
incidents
otel_cumulative_state
pull_requests
review_events
webhook_deliveries
workflow_runs
```

(Verified by autogenerate — all 10 model exports + the two internal models
`OtelCumulativeState` and `WebhookDelivery` are picked up by
`Base.metadata`.)

## Test cases

### T1 — `alembic upgrade head` against SQLite (in-memory)

```bash
$ DORA_DATABASE_URL="sqlite:///:memory:" \
    DORA_GITHUB_TOKEN=dummy DORA_GITHUB_REPOS=x/y \
    DORA_GITHUB_WEBHOOK_SECRET=dummy DORA_API_KEY=dummy \
    DORA_AUTO_MIGRATE=true \
    python -c "from app.main import _check_or_apply_migrations as f; f()"
DORA_AUTO_MIGRATE=true → running alembic upgrade head
INFO alembic Running upgrade  -> deb41848adf6, initial schema
OK: auto-migrate applied
```

✅ Auto-migrate path works.

### T2 — Lifespan refuses to start on unmigrated DB

```bash
$ DORA_DATABASE_URL="sqlite:///:memory:" ... \
    python -c "from app.main import _check_or_apply_migrations; _check_or_apply_migrations()"
ERROR app.main: Database has no Alembic revision applied. Run
  `alembic upgrade head` (or set DORA_AUTO_MIGRATE=true) before starting
  the backend.
RuntimeError: schema not migrated
```

✅ Empty DB → backend refuses to start with a clear error.

### T3 — Fresh upgrade against in-cluster postgres on `dora-trial`

Created a fresh database on the live trial cluster postgres pod:

```bash
$ kubectl -n dora-metrics exec postgres-... -- \
    psql -U dora -d dora_metrics -c "CREATE DATABASE dora_test_phase3;"
CREATE DATABASE

$ kubectl -n dora-metrics port-forward svc/postgres 15432:5432 &
$ DORA_DATABASE_URL="postgresql+psycopg2://dora:***@localhost:15432/dora_test_phase3" \
    alembic upgrade head
INFO alembic Running upgrade  -> deb41848adf6, initial schema

$ kubectl -n dora-metrics exec postgres-... -- \
    psql -U dora -d dora_test_phase3 -c "\dt"
                List of relations
 Schema |         Name          | Type  | Owner
--------+-----------------------+-------+-------
 public | alembic_version       | table | dora
 public | alert_events          | table | dora
 public | alert_rules           | table | dora
 public | claude_code_sessions  | table | dora
 public | commits               | table | dora
 public | deployments           | table | dora
 public | dora_level_snapshots  | table | dora
 public | incidents             | table | dora
 public | otel_cumulative_state | table | dora
 public | pull_requests         | table | dora
 public | review_events         | table | dora
 public | webhook_deliveries    | table | dora
 public | workflow_runs         | table | dora
(13 rows)
```

✅ All 12 app tables + `alembic_version` created against a real Postgres 16.

### T4 — Stamp upgrade for existing DBs

The live `dora_metrics` DB on `dora-trial` was already populated by the old
`Base.metadata.create_all()` lifespan, so a naive `upgrade head` fails with
`relation "alert_events" already exists`. Correct path:

```bash
$ alembic stamp head
INFO alembic Running stamp_revision  -> deb41848adf6
$ alembic current
deb41848adf6 (head)
$ alembic upgrade head
# (no-op, no migrations to run)
```

✅ Documented in `docs/EKS-DEPLOY.md` upgrade section.

### T5 — Migrate Job kustomize render

Both overlays still render cleanly with the migrate-job added:

```bash
$ kubectl kustomize infra/k8s/overlays/trial > /tmp/t.yaml
$ kubectl kustomize infra/k8s/overlays/production > /tmp/p.yaml
$ grep -E "kind: Job|kind: Deployment" /tmp/t.yaml
kind: Deployment   # dora-backend
kind: Deployment   # dora-frontend
kind: Job          # dora-migrate
$ grep -E "image:" /tmp/t.yaml | grep dora-backend
        image: dora-backend:placeholder   # backend container
        image: dora-backend:placeholder   # migrate-job container — same image
```

✅ kustomize `images:` transformer covers both Deployment and Job.

### T6 — Server-side dry-run of migrate-job

```bash
$ kubectl kustomize infra/k8s/overlays/trial \
  | kubectl apply --server-side --dry-run=server -f -
job.batch/dora-migrate serverside-applied (server dry run)
... (other resources)
```

✅ Migrate Job validates server-side.

## Issues addressed

| Issue | Status | Notes |
|-------|--------|-------|
| #31 Alembic missing despite being in requirements | ✅ Resolved | Initial migration `0001_initial_schema` covers all 12 tables; lifespan now refuses to start on unmigrated DB; new `migrate-job.yaml` runs `alembic upgrade head` before backend becomes ready |

## Notes / lessons

1. The previous codepath (`Base.metadata.create_all`) silently created
   tables on every restart, which masks schema drift. Removing it surfaces
   missing migrations as a hard error — much better signal.
2. **Existing trial deployments need `alembic stamp head` once** before
   they upgrade to this version; otherwise the migrate Job will fail with
   `DuplicateTable`. Documented as an upgrade note.
3. The migrate Job uses the same image and SA as the backend Deployment,
   so it inherits IRSA in production (no extra IAM wiring needed).
4. `DORA_AUTO_MIGRATE=true` is convenient for trial mode but should be
   `false` (default) in production — the Job is the single source of truth
   for schema changes there.
