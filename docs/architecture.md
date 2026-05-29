# DORA Metrics Platform - Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES                                       │
├─────────────┬──────────────┬──────────────────┬─────────────────────────────┤
│ Claude Code │   GitHub     │   CI/CD Tools    │   Incident Management       │
│ (OTel/API)  │  (Webhooks)  │ (Actions/Jenkins)│   (PagerDuty/OpsGenie)      │
└──────┬──────┴──────┬───────┴────────┬─────────┴──────────────┬──────────────┘
       │             │                │                         │
       ▼             ▼                ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ OTel         │  │ GitHub       │  │ CI/CD        │  │ Incident     │   │
│  │ Collector    │  │ Webhook Recv │  │ Collector    │  │ Collector    │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
└─────────┼──────────────────┼─────────────────┼─────────────────┼───────────┘
          │                  │                 │                  │
          ▼                  ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PROCESSING ENGINE                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Event Store (PostgreSQL)                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Deploy Freq  │  │ Lead Time    │  │ Change Fail  │  │ MTTR         │   │
│  │ Calculator   │  │ Calculator   │  │ Calculator   │  │ Calculator   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         └──────────────────┴─────────────────┴─────────────────┘           │
│                                    │                                        │
│                      ┌─────────────▼──────────────┐                        │
│                      │   Event Store               │                        │
│                      │      (PostgreSQL 15+)       │                        │
│                      └─────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API LAYER (FastAPI)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  GET /api/v1/metrics/dora          - All 4 DORA metrics summary             │
│  GET /api/v1/metrics/deploy-freq   - Deployment frequency over time         │
│  GET /api/v1/metrics/lead-time     - Lead time for changes                  │
│  GET /api/v1/metrics/change-fail   - Change failure rate                    │
│  GET /api/v1/metrics/mttr          - Mean time to recovery                  │
│  GET /api/v1/metrics/claude-code   - Claude Code specific telemetry         │
│  GET /api/v1/teams                 - Team/repo configuration                │
│  POST /api/v1/webhooks/github      - GitHub webhook receiver                │
│  POST /api/v1/webhooks/otel        - OTLP HTTP receiver                     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐           │
│  │  Overview   │  │  Deploy    │  │  Lead Time │  │  Failure   │           │
│  │  Dashboard  │  │  Frequency │  │  Trends    │  │  Rate      │           │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘           │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────────┐           │
│  │  MTTR      │  │ Claude Code│  │  Team/Repo Configuration   │           │
│  │  Analysis  │  │ Analytics  │  │                            │           │
│  └────────────┘  └────────────┘  └────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Descriptions

### 1. Data Source Collectors

| Module | Purpose | Data Collected |
|--------|---------|----------------|
| **Claude Code OTel Collector** | Receives OpenTelemetry metrics/events from Claude Code | Sessions, commits, PRs, LOC, tokens, cost, tool decisions |
| **GitHub Webhook Receiver** | Captures GitHub events via webhooks | PR opened/merged/closed, commits, reviews, deployments |
| **CI/CD Collector** | Polls or receives CI/CD pipeline data | Build success/failure, deploy timestamps, pipeline duration |
| **Incident Collector** | Integrates with incident management | Incident start/end, severity, affected services |

### 2. Processing Engine

| Module | Purpose | DORA Metric |
|--------|---------|-------------|
| **Deploy Frequency Calculator** | Counts successful deployments per time period | Deployment Frequency |
| **Lead Time Calculator** | Measures first commit → production deploy duration | Lead Time for Changes |
| **Change Failure Calculator** | Ratio of failed deployments to total | Change Failure Rate |
| **MTTR Calculator** | Time from incident detection to recovery | Mean Time to Recovery |

### 3. Storage

| Component | Purpose |
|-----------|---------|
| **PostgreSQL 15+** | Event store, raw webhook data, OTLP cumulative state, webhook delivery dedupe table. Time-series queries are served by composite indexes on `(repo, *_at)`; we have not needed TimescaleDB at the volumes this platform sees. |

### 4. API Layer (FastAPI)

| Endpoint Group | Purpose |
|----------------|---------|
| `/api/v1/metrics/*` | DORA metric queries with time range and team filters |
| `/api/v1/webhooks/*` | Webhook receivers for GitHub, OTel, CI/CD |
| `/api/v1/teams` | Team and repository management |
| `/api/v1/claude-code` | Claude Code specific analytics |

### 5. Frontend (React)

| Page | Purpose |
|------|---------|
| **Overview Dashboard** | 4 DORA metrics at a glance with DORA level rating |
| **Deploy Frequency** | Deployment trend chart, per-repo breakdown |
| **Lead Time** | P50/P95 lead time, bottleneck analysis |
| **Change Failure Rate** | Failure trends, root cause categories |
| **MTTR** | Recovery time trends, incident correlation |
| **Claude Code Analytics** | AI-assisted development metrics |

## DORA Metric Data Requirements

### Deployment Frequency
- **From GitHub**: Merged PRs to main/production branches, GitHub Deployments API events
- **From CI/CD**: Successful production pipeline completions
- **From Claude Code**: `pull_requests_by_claude_code` (contribution tracking)

### Lead Time for Changes
- **From GitHub**: First commit timestamp on branch, PR creation time, PR merge time
- **From CI/CD**: Deploy completion timestamp
- **Calculation**: `deploy_timestamp - first_commit_timestamp`

### Change Failure Rate
- **From CI/CD**: Failed deployments / total deployments
- **From GitHub**: Reverts, hotfix PRs
- **From Incidents**: Deployment-correlated incidents

### Mean Time to Recovery
- **From Incidents**: Incident created timestamp
- **From GitHub**: Fix PR merged timestamp
- **From CI/CD**: Recovery deploy timestamp
- **Calculation**: `recovery_timestamp - incident_start_timestamp`

### Claude Code Contribution Metrics (Enhancement)
- Sessions per developer per day
- Lines of code added/removed via Claude Code
- Tool acceptance rate (code quality proxy)
- Commits/PRs created with Claude Code assistance
- Token cost per developer

## Deployment Options

1. **Local (Docker Compose)** - Single machine, all services in containers
2. **AWS EKS** - Kubernetes deployment with Helm charts
3. **Bare metal** - Direct Python/Node.js processes
