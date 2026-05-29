# DORA Metrics Platform

End-to-end platform for measuring engineering performance using DORA (DevOps Research and Assessment) metrics — with first-class integration for **GitHub** and **Claude Code AI telemetry**.

[![CI](https://github.com/REPLACE_OWNER/dora-metrics-platform/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![CodeQL](https://github.com/REPLACE_OWNER/dora-metrics-platform/actions/workflows/codeql.yml/badge.svg)](.github/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

Answers four questions about a team using a dashboard:

| DORA metric | Question |
|-------------|----------|
| Deployment Frequency | How often do we ship? |
| Lead Time for Changes | How long from commit to production? |
| Change Failure Rate | How often does a deploy break things? |
| Mean Time to Recovery | How fast do we recover from incidents? |

It also surfaces **AI-assisted development** signals from Claude Code (sessions, accept/reject rate, lines of code, cost) so you can correlate AI usage with delivery metrics.

## Architecture

```
GitHub (webhook + REST polling)  ──┐
GitHub Actions (CI/CD)             ├──►  FastAPI backend  ──►  PostgreSQL
Claude Code (Admin API + OTel)     ┤              │
Incident sources (optional)        ┘              ▼
                                          React dashboard (Vite + Tailwind + Recharts)
```

Full architecture: [docs/architecture.md](docs/architecture.md).
Threat model and hardening: [SECURITY.md](SECURITY.md) and [docs/SECURITY-HARDENING.md](docs/SECURITY-HARDENING.md).

## Quick start (Docker Compose)

```bash
# 1. Configure
cp backend/.env.example .env
python -c "import secrets; print('DORA_GITHUB_WEBHOOK_SECRET=' + secrets.token_hex(32))" >> .env
python -c "import secrets; print('DORA_API_KEY=' + secrets.token_urlsafe(48))" >> .env
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))" >> .env
# Edit .env: set DORA_GITHUB_TOKEN and DORA_GITHUB_REPOS

# 2. Launch
docker compose up -d --build

# 3. Open
open http://localhost:3000
```

The compose file **refuses to start** if required secrets aren't set — by design.

## Local development

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in real values
uvicorn app.main:app --reload

# Frontend
cd frontend && npm ci && npm run dev
```

## Deploy to AWS EKS

See [docs/EKS-DEPLOY.md](docs/EKS-DEPLOY.md) for the full secure deployment runbook (RDS, IRSA, External Secrets, ALB+ACM, WAF, NetworkPolicy).

Short version:

```bash
# Build & push
aws ecr create-repository --repository-name dora-backend
aws ecr create-repository --repository-name dora-frontend
docker build -f infra/docker/Dockerfile.backend  -t $ECR/dora-backend:$TAG .
docker build -f infra/docker/Dockerfile.frontend -t $ECR/dora-frontend:$TAG .
docker push $ECR/dora-backend:$TAG && docker push $ECR/dora-frontend:$TAG

# Deploy (after substituting env vars in manifests)
kubectl apply -k infra/k8s
```

## DORA metric sources

| Metric | Primary source | Fallback |
|--------|---------------|----------|
| Deployment Frequency | GitHub Deployments API | Merged PRs to default branch |
| Lead Time for Changes | PR `first_commit_at` → `merged_at` | PR `created_at` → `merged_at` |
| Change Failure Rate | CI failure rate on main + revert PRs | Revert/hotfix ratio |
| Mean Time to Recovery | Incident management webhooks | Hotfix PR `created_at` → `merged_at` |
| AI contribution | Claude Code Admin API (`sk-ant-admin-*`) | OpenTelemetry collector |

### Beyond GitHub-only: two signals you should plug in

If you only point this at a GitHub repo, every number on the dashboard is derived from GitHub data alone — and two of the four DORA metrics are running on **proxies**, not ground truth. To get meaningful numbers, plug in two more sources:

1. **Real deployment events** — don't rely on merged PRs as a deploy proxy.
   Have your CI/CD `POST /api/v1/deployments` (or call the GitHub Deployments API) when something *actually* ships to prod. Without this, **Deployment Frequency** counts merges (not releases), and **Lead Time** measures `first_commit → merged_at` instead of `first_commit → live_in_prod`.

2. **Incident source** — wire up PagerDuty / OpsGenie / your on-call tool.
   Without real incidents, **MTTR** falls back to "hotfix PR open → merge duration", which is a heuristic at best (`is_hotfix` is detected from PR title/branch keywords). Real incident timestamps give you true `detected → resolved` recovery times.

Until both are connected, treat the dashboard as a **directional** signal — useful for trends, not for benchmarking against the published DORA cohorts.

## API endpoints

All `GET /api/v1/metrics/*` are public read-only. Mutating endpoints require `X-API-Key`. The webhook requires HMAC-SHA256 signature.

| Endpoint | Auth |
|----------|------|
| `GET /health` | none |
| `GET /api/v1/metrics/dora` | none |
| `GET /api/v1/metrics/{deploy-freq,lead-time,change-fail,mttr,timeline}` | none |
| `GET /api/v1/metrics/claude-code` | none |
| `GET /api/v1/reviews` | none |
| `GET /api/v1/repos` | none |
| `POST /api/v1/collect/github` | `X-API-Key` |
| `POST /api/v1/collect/claude-code` | `X-API-Key` |
| `POST /api/v1/webhooks/github` | `X-Hub-Signature-256` HMAC |

Repo query params are validated against `DORA_GITHUB_REPOS` — you cannot query repos this server isn't configured for.

## Security

A short summary; see [SECURITY.md](SECURITY.md) for the full policy.

- gitleaks pre-commit hook + CI secret scan
- CodeQL (Python + JS) + Bandit + npm audit + Trivy (containers) + Kubescape (manifests) in CI
- Webhook HMAC verification is **mandatory** (fails closed)
- API key required for mutating endpoints (fails closed)
- CORS strict allowlist — wildcard rejected at startup
- Containers: non-root, read-only root FS, drop all caps, seccomp RuntimeDefault, multi-stage builds
- Kubernetes: Pod Security Standard `restricted` enforced, NetworkPolicy default-deny, External Secrets from AWS Secrets Manager, ALB with TLS 1.3
- Dependabot weekly for pip / npm / Docker / Actions

## Project structure

```
dora-metrics-platform/
├── backend/                          FastAPI service
│   └── app/
│       ├── api/{routes,security}.py  Endpoints + auth helpers
│       ├── collectors/               GitHub + Claude Code clients
│       ├── models/                   SQLAlchemy schema
│       ├── services/dora_calculator  DORA math
│       └── main.py                   App + scheduler
├── frontend/                         React + Vite dashboard
├── infra/
│   ├── docker/                       Hardened multi-stage Dockerfiles + nginx
│   └── k8s/                          EKS manifests (kustomize)
├── otel-collector/                   OpenTelemetry config (optional)
├── docs/                             Architecture + EKS + telemetry guides
├── .github/                          CI workflows + Dependabot
└── docker-compose.yml                Local-only stack
```

## License

[MIT](LICENSE)
