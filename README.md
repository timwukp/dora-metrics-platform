# DORA Metrics Platform

End-to-end platform for measuring engineering performance using DORA (DevOps Research and Assessment) metrics — with first-class integration for **GitHub** and **Claude Code AI telemetry**.

[![CI](https://github.com/timwukp/dora-metrics-platform/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![CodeQL](https://github.com/timwukp/dora-metrics-platform/actions/workflows/codeql.yml/badge.svg)](.github/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **[繁體中文版 (Traditional Chinese)](README.zh-TW.md)**

## Why DORA metrics?

Most engineering teams ship code every day but can't answer basic questions: *Are we actually getting faster? Is quality improving or declining? How do we compare to industry benchmarks?*

**DORA metrics** (from Google Cloud's DevOps Research and Assessment program) are the industry standard for measuring software delivery performance. Based on 7+ years of research across 36,000+ professionals, the data shows that elite-performing teams:

- Ship **973x more frequently** than low performers
- Recover from failures **6,570x faster**
- Have **3x lower change failure rates**
- Deliver code to production **6,570x faster** (from commit to deploy)

These aren't vanity metrics. The research directly correlates DORA performance with **business outcomes**: revenue growth, profitability, market share, and customer satisfaction.

### What DORA measures and why it matters

| Metric | What it tells you | Business impact |
|--------|-------------------|-----------------|
| **Deployment Frequency** | How often your team delivers value to users | Faster time-to-market, quicker feedback loops |
| **Lead Time for Changes** | How long ideas take to reach production | Competitive agility, reduced opportunity cost |
| **Change Failure Rate** | How often deployments cause problems | Customer trust, engineering confidence, cost of rework |
| **Mean Time to Recovery** | How fast you bounce back from incidents | Revenue protection, SLA compliance, customer retention |

### The problem this platform solves

Without a measurement platform, teams fall into one of two traps:

1. **Flying blind** — No data on delivery performance. Improvement is anecdotal. Leadership can't distinguish "we feel busy" from "we're actually delivering value faster."

2. **Spreadsheet metrics** — Someone manually pulls data from GitHub, Jira, and PagerDuty into a quarterly report. By the time it's ready, it's stale and unactionable.

This platform provides **automated, real-time DORA metrics** by connecting directly to your existing tools (GitHub, CI/CD, incident management). No manual data entry. No spreadsheets. Teams see their performance weekly, spot regressions early, and track the impact of process improvements.

### Using DORA with Scrum teams

DORA metrics and Scrum are naturally complementary. Scrum provides cadence; DORA provides objective measurement. Together, they transform Sprint Retrospectives from "I feel like..." into "the data shows...".

**Mapping to Scrum ceremonies:**

| Ceremony | How DORA helps | How to use this platform |
|----------|---------------|--------------------------|
| **Sprint Planning** | Reference past Lead Time and deploy frequency to estimate team throughput | Query with `days=14` for last Sprint's baseline |
| **Sprint Review** | Show actual delivery volume (not just story points) | Dashboard Deployment Frequency card |
| **Sprint Retrospective** | Pinpoint bottlenecks: slow coding? Reviews stuck? Deploy pipeline broken? | Timeline trend charts + Lead Time breakdown (coding vs review time) |
| **Cross-Sprint tracking** | Track whether improvements persist over multiple Sprints | Weekly trend charts spanning multiple Sprints |

**Practical recommendations:**

1. **Open the Dashboard at every Retro** — Set the time range to your Sprint length (e.g., 14 days). Check if any of the four metrics regressed. Pay special attention to Lead Time breakdown: if review time accounts for 70%, the bottleneck isn't development speed — it's your code review process.

2. **Set incremental goals using DORA levels** — Don't aim for Elite on day one. Start from your baseline and improve one level every few Sprints. Example: "Reduce Lead Time from Medium (1 week) to High (1 day) over the next 3 Sprints."

3. **Use Deployment Frequency as a Sprint health indicator** — A sudden drop may signal stories are too large, PRs are too big, or there's a blocker. Trend charts help you compare across Sprints to see patterns, not noise.

4. **DORA is a team improvement tool, not a performance review** — The DORA research team explicitly states these metrics help teams inspect and adapt, not punish individuals. This aligns with Scrum's core principle: focus on process improvement, not blame.

**DORA performance levels (as improvement targets, not grading criteria):**

| Level | Deploy Frequency | Lead Time | Change Failure Rate | Recovery Time |
|-------|-----------------|-----------|--------------------:|---------------|
| Elite | Multiple per day | < 1 hour | < 5% | < 1 hour |
| High | Daily to weekly | 1 day - 1 week | 5-10% | < 1 day |
| Medium | Weekly to monthly | 1 week - 1 month | 10-15% | 1 day - 1 week |
| Low | > Monthly | > 1 month | > 15% | > 1 week |

Most teams start at Medium. The goal is to move up one level every few Sprints — not to jump straight to Elite.

### Who benefits

| Role | What they get |
|------|---------------|
| **Engineering leaders / VP Eng** | Data-driven conversations about team capacity, investment decisions, and improvement initiatives |
| **Platform / DevOps teams** | Validate that infrastructure investments (CI speed, deploy automation, observability) actually improve delivery |
| **Product development teams** | Self-service dashboard to track their own trends without waiting for quarterly reports |
| **Executives** | Correlate engineering investment with delivery throughput and reliability |

## What it does

Answers four questions about a team using a dashboard:

| DORA metric | Question |
|-------------|----------|
| Deployment Frequency | How often do we ship? |
| Lead Time for Changes | How long from commit to production? |
| Change Failure Rate | How often does a deploy break things? |
| Mean Time to Recovery | How fast do we recover from incidents? |

It also surfaces **AI-assisted development** signals from Claude Code (sessions, accept/reject rate, lines of code, cost) so you can correlate AI usage with delivery metrics.

### Beyond the four metrics

The dashboard also includes:

- **Sprint-aligned views** — pick a sprint window from a configured schedule (`DORA_SPRINT_SCHEDULE="<anchor-iso-date>:<length-days>"`); falls back to "Last N days" when unset.
- **DORA regression alerts** — define rules per repo/metric; the daily evaluator fires when a threshold is breached AND (optionally) the metric moved by `change_pct` vs. the prior equal-length window. Slack and email channels with stub-mode default. 7-day dedup window.
- **Weekly DORA level snapshots** — a heatmap showing how each metric's level (Elite / High / Medium / Low) drifted over the last 26 weeks. Snapshots are idempotent per `(repo, metric, week_start)` and self-heal if a daily run was missed.
- **Incident webhook receivers** — PagerDuty and OpsGenie post incident lifecycle events (HMAC-SHA256 verified, replay-safe). MTTR is then computed from real `triggered → resolved` timestamps instead of hotfix-PR proxies.
- **Retro markdown export** — one-click download of `dora-retro-<window>.md` with headline metrics, breakdown, and rule-based discussion suggestions (high CFR, review-dominated lead time, etc.).
- **Compare across teams** — direction-only trend arrows (↑/↓/→) for every configured repo, designed to surface _shared bottlenecks_ rather than rank teams.

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

### Prerequisites

The shipped manifests assume these are installed in your cluster:

```bash
# AWS Load Balancer Controller (for the Ingress)
helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system --set clusterName=$CLUSTER

# External Secrets Operator (for AWS Secrets Manager → K8s Secret sync)
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

Plus a CNI that enforces NetworkPolicy (Calico, Cilium, or VPC CNI in policy mode).
**EKS Fargate-only clusters do NOT enforce NetworkPolicy** — see [docs/EKS-DEPLOY.md](docs/EKS-DEPLOY.md#fargate-clusters).

### Short version

```bash
# 1. Build & push (linux/amd64 required for Fargate; Apple Silicon defaults to arm64)
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export TAG=$(git rev-parse --short HEAD)
./scripts/build-and-push.sh

# 2. Render manifests (envsubst + fail-loud on unresolved REPLACE_* placeholders)
export IMAGE_TAG=$TAG
./scripts/render-manifests.sh

# 3. Apply
kubectl apply -f build/k8s/
```

For a minimal **trial-mode** deployment without ALB/ACM/WAF (port-forward only),
see [docs/EKS-DEPLOY.md → Trial mode](docs/EKS-DEPLOY.md#trial-mode-port-forward-only).

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
| `GET /api/v1/metrics/level-history` | none |
| `GET /api/v1/reviews` | none |
| `GET /api/v1/repos` | none |
| `GET /api/v1/sprints` | none |
| `GET /api/v1/reports/retro` | none |
| `GET /api/v1/alerts/rules` / `/alerts/events` | none |
| `POST /api/v1/collect/github` | `X-API-Key` |
| `POST /api/v1/collect/claude-code` | `X-API-Key` |
| `POST /api/v1/collect/level-snapshots` | `X-API-Key` |
| `POST /api/v1/alerts/rules` / `DELETE /alerts/rules/{id}` | `X-API-Key` |
| `POST /api/v1/alerts/evaluate` | `X-API-Key` |
| `POST /api/v1/webhooks/github` | `X-Hub-Signature-256` HMAC |
| `POST /api/v1/webhooks/pagerduty` | `X-PagerDuty-Signature` HMAC (optional) |
| `POST /api/v1/webhooks/opsgenie` | `X-OpsGenie-Token` (optional) |

Repo query params are validated against `DORA_GITHUB_REPOS` — you cannot query repos this server isn't configured for.

### Configuration for the new features

| Setting | Purpose | Default |
|---------|---------|---------|
| `DORA_SPRINT_SCHEDULE` | `<anchor-iso-date>:<length-days>` (e.g. `2026-01-06:14`). Empty hides the sprint selector. | unset |
| `DORA_ALERTS_ENABLED` | Master switch for the alert dispatcher. When `false`, channels stub-log instead of sending. | `false` |
| `DORA_ALERTS_SLACK_WEBHOOK` | Slack incoming-webhook URL. | unset |
| `DORA_ALERTS_EMAIL_TO` / `DORA_ALERTS_SMTP` | Email recipients + `host:port`. SMTP delivery is a hook in trial mode. | unset |
| `DORA_PAGERDUTY_WEBHOOK_SECRET` | HMAC secret for V3 webhook subscription. Unset = accept unsigned (dev only). | unset |
| `DORA_OPSGENIE_WEBHOOK_SECRET` | Token compared against `X-OpsGenie-Token`. | unset |
| `DORA_INCIDENT_DEFAULT_REPO` | Repo to attribute incidents to when payload lacks a service→repo mapping. | first configured repo |

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

## Methodology for AI-assisted development

This repo treats AI coding agents (Claude Code, Cursor, Codex, Aider, etc.)
as first-class collaborators. Two short methodology documents, paired,
make it possible to start a fresh agent session — or onboard a new
contributor — without re-explaining context every time:

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | The repo's invariants, deployment topology, dev loop, and doc index. Read this on arrival. |
| [`docs/methodology/agent-onboarding.md`](docs/methodology/agent-onboarding.md) | **Context durability.** A repo-agnostic pattern for making any project legible to AI agents — `AGENTS.md` structure + `discussion`-issue template (Working assumptions + Repo context). |
| [`docs/methodology/change-discipline.md`](docs/methodology/change-discipline.md) | **Change discipline.** A 5-step DISCOVER → TRIAGE → GROUP → FIX → REVIEW loop, branch / commit / PR conventions, anti-patterns, and stacked-PR exception. Worked example: the phase 1–6 install-friction stack (PRs #34–#38, closing issues #23–#33). |

The two are **orthogonal and complementary**: agent-onboarding makes
sure agents *understand* the repo; change-discipline makes sure they
*land changes* the same way humans do. Together they form a complete
agentic dev kit.

GitHub forms in this repo also enforce the discipline: see
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE) (bug, enhancement,
discussion templates) and [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).

**To apply this pattern to another repo:** copy the two methodology
docs verbatim, then write that repo's own `AGENTS.md` using the
8-section template at the top of `agent-onboarding.md`. The
methodology files are deliberately repo-agnostic.

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
