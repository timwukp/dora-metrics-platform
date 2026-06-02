# Agent Onboarding

This file is the entry point for any AI coding agent or human developer
joining this repository for the first time. Read it once before
making changes — it captures invariants, constraints, and the
deployment topology that are not obvious from the code alone.

If you only have time for one section, read **Invariants** below.

---

## What this project is

`dora-metrics-platform` is an end-to-end platform for measuring
engineering delivery performance using DORA (DevOps Research and
Assessment) metrics. It connects to GitHub and Claude Code telemetry,
stores aggregates in PostgreSQL, and serves a React dashboard.

- **Backend:** FastAPI + APScheduler + SQLAlchemy 2.0, deployed on
  EKS Fargate
- **Frontend:** React + Vite, served via nginx
- **Database:** PostgreSQL (in-cluster for trial; RDS for production)
- **Migrations:** Alembic (Postgres only — unit tests use SQLite +
  `Base.metadata.create_all` and skip Alembic checks)

For functional details see [`README.md`](README.md) and
[`docs/architecture.md`](docs/architecture.md).

---

## Invariants — do not violate without explicit approval

These are repo-wide constraints. They are non-negotiable in normal
work and require an explicit conversation with the maintainer to
relax.

| # | Invariant | Why |
|---|---|---|
| 1 | **If you fork or adapt this repo for your own deployment, keep your fork PRIVATE.** This upstream repo is public on purpose (showcase + methodology reference). | Once you fill in real AWS account IDs, cluster ARNs, secrets, or webhook tokens, the placeholders become real values — and a public fork would expose them. |
| 2 | **Trial mode is port-forward only.** No public Ingress, no ALB, no public LoadBalancer in the trial overlay or trial Helm preset. | The trial deployment is for evaluation; exposing endpoints multiplies the attack surface and the threat model in `SECURITY.md` doesn't cover open ingress for trial. |
| 3 | **API key files are `chmod 600`.** `scripts/trial-bootstrap.sh` writes `~/.config/dora/apikey` at 600 — preserve this when touching install scripts. | Anyone with read access to the home dir would otherwise inherit auth. |
| 4 | **No new AWS services beyond what trial currently uses.** Current set: EKS, ECR, IAM (IRSA), CloudWatch (logs only at present). New services need an issue + maintainer approval. | Keeps the trial install one-command and the cost model predictable. |
| 5 | **No secrets in the repo.** No tokens, passwords, certificates, or API keys committed to any branch. gitleaks runs on every PR — if it fires, the secret is the bug, not the scanner. | A leaked credential is a permanent leak (git history, mirrors, forks). |
| 6 | **Webhook HMAC verification is required, not optional.** `DORA_GITHUB_WEBHOOK_SECRET` must be set or the webhook endpoint refuses all requests. Don't add a "skip verification" flag. | See `SECURITY.md` threat model row 1. |
| 7 | **CORS allowlist must be exact origins.** No `*` with credentials. The startup check rejects `*`. | Same threat model. |
| 8 | **Don't bypass git-defender by skipping hooks.** This repo has a `git push` hook that blocks ordinary pushes — use the GitHub Git Data API via `gh api` (`/git/blobs`, `/git/trees`, `/git/commits`, `/git/refs`) for writes. See [`docs/EKS-DEPLOY.md`](docs/EKS-DEPLOY.md) for the rationale. | `--no-verify` defeats the protection that's there for a reason. |

---

## Deployment topology

The trial cluster is a real EKS Fargate cluster in `us-east-1`. The
account ID and cluster name are intentionally **not** committed —
look at the maintainer's local `~/.config/dora/` or ask. What's
public:

- **Trial preset** (`helm/dora-metrics/values-trial.yaml`,
  `infra/k8s/overlays/trial/`):
  - In-cluster Postgres on `emptyDir`
  - Backend `Deployment` 1/1 + frontend `Deployment` 1/1
  - No Ingress; reach the dashboard via
    `kubectl port-forward svc/dora-frontend 8080:80`
  - Migrations: optional one-shot `Job` running `alembic upgrade head`
- **Production preset** (`values-production.yaml`,
  `overlays/production/`):
  - External RDS Postgres
  - IRSA service accounts
  - ALB Ingress with ACM TLS
  - Migrations: `Job` is required, gated by lifespan check

For the full step-by-step see [`docs/EKS-DEPLOY.md`](docs/EKS-DEPLOY.md).

---

## Local development loop

What contributors actually run while iterating. All commands are run
from the repo root unless noted.

```bash
# Backend tests (SQLite, in-process — no Docker needed)
cd backend && pytest -q

# Backend lint
cd backend && ruff check . && black --check .

# Frontend build + lint
cd frontend && npm ci && npm run lint && npm run build

# Helm chart lint (both presets)
helm lint helm/dora-metrics -f helm/dora-metrics/values-trial.yaml
helm lint helm/dora-metrics -f helm/dora-metrics/values-production.yaml

# Kustomize render (both overlays)
kubectl kustomize infra/k8s/overlays/trial
kubectl kustomize infra/k8s/overlays/production

# Full local stack via docker-compose
docker compose up
```

CI runs all of the above on every PR. If a check goes red on a PR
you authored, fix the underlying cause — don't `--no-verify` past it.

When building images for the trial cluster, **explicitly target
`linux/amd64`** even on Apple Silicon — Fargate is amd64 only and
multi-arch manifests have failed to pull on `dora-trial` historically.

```bash
docker buildx build --platform linux/amd64 -t <ecr>/<repo>:<tag> --push .
```

---

## How decisions are recorded

This project deliberately does not maintain a separate ADR directory.
Decisions live in three places:

1. **GitHub issues with the `discussion` or `enhancement` label** —
   open architectural questions waiting for the next iteration. Read
   any open `discussion` issues before changing related code; the
   maintainer's working assumptions are written into them.
2. **Phase test reports under `docs/test-reports/`** — what was
   actually built, what was tested, what was left as a follow-up.
   The latest rollup is
   [`docs/test-reports/phase6-rollup.md`](docs/test-reports/phase6-rollup.md).
3. **Commit messages and PR descriptions** — the *why* for any
   non-obvious change. Don't squash this context into one-liners.

If you're about to make a non-trivial change and can't find the
*why* in any of the three above, that's a signal to either open a
new issue or ask before coding.

**Before opening an issue or PR, read
[`docs/methodology/change-discipline.md`](docs/methodology/change-discipline.md)** —
it covers issue granularity, PR sizing, branch naming, and the
templates under `.github/`.

---

## Communication conventions

- **Be terse.** The maintainer prefers short, dense responses to
  long narrative ones. Save the prose for issues and PR descriptions
  where it gets reviewed.
- **Pin claims to file paths and line numbers** (`backend/app/main.py:142`)
  rather than describing where something is.
- **When uncertain, ask one question and stop.** Don't speculate
  across multiple paths — narrow the question first.
- **Match scope to ask.** A bug fix is a bug fix; don't bundle
  unrelated cleanup, refactors, or "while I'm here" changes unless
  the maintainer asks for them.

---

## Where to look next

| Looking for… | Read… |
|---|---|
| What the system does and why | [`README.md`](README.md), [`docs/architecture.md`](docs/architecture.md) |
| Security baseline | [`SECURITY.md`](SECURITY.md), [`docs/SECURITY-HARDENING.md`](docs/SECURITY-HARDENING.md) |
| How to deploy on EKS | [`docs/EKS-DEPLOY.md`](docs/EKS-DEPLOY.md) |
| How telemetry is collected | [`docs/telemetry.md`](docs/telemetry.md), [`docs/telemetry-requirements.md`](docs/telemetry-requirements.md) |
| What was built recently and how | [`docs/test-reports/`](docs/test-reports/) |
| Open architectural questions | [GitHub issues with `discussion` or `question` label](../../issues?q=is%3Aissue+label%3Adiscussion%2Cquestion) |
| How to file an issue or open a PR (process) | [`docs/methodology/change-discipline.md`](docs/methodology/change-discipline.md) |
| The methodology behind this onboarding doc | [`docs/methodology/agent-onboarding.md`](docs/methodology/agent-onboarding.md) |

---

## For agents specifically

If you are an AI coding agent (Claude Code, Cursor, Codex, Aider,
etc.) reading this:

1. **Read this whole file.** It's short on purpose.
2. **Skim the doc index above** — at minimum `SECURITY.md` and
   `docs/EKS-DEPLOY.md` if you'll touch infra.
3. **Check open issues with the `discussion` label** before changing
   code in any area that has one. The maintainer's working
   assumptions are written into them.
4. **Follow the change-discipline workflow** in
   [`docs/methodology/change-discipline.md`](docs/methodology/change-discipline.md):
   audit broadly, file findings as separate issues, one logical
   change per PR. Stacked PRs are an exception, not a default.
5. **Don't invent context.** If something isn't documented, ask.
6. **Don't write planning docs unless asked.** Don't create
   `IMPLEMENTATION-PLAN.md` or `CHANGES.md` files. Use the conversation
   and the PR description.
