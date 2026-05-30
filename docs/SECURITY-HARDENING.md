# Security Hardening Reference

This document enumerates every defense layer and where it is implemented, so a reviewer or auditor can verify each control.

## 1. Source-code layer

| Control | Where |
|---------|-------|
| `.gitignore` covers env, virtualenvs, build artifacts, IDE files | `.gitignore` |
| `.dockerignore` prevents leaking secrets/dev artifacts into images | `.dockerignore` |
| Pre-commit hooks: gitleaks, ruff, bandit, hadolint, detect-private-key | `.pre-commit-config.yaml` |
| Gitleaks config tuned for project | `.gitleaks.toml` |
| CODEOWNERS for review enforcement | `CODEOWNERS` |
| SECURITY.md disclosure policy | `SECURITY.md` |

## 2. Continuous integration

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | ruff + bandit + import smoke test + npm audit + frontend build |
| `codeql.yml` | GitHub CodeQL (Python + JS) — security-and-quality query pack |
| `secret-scan.yml` | gitleaks on every PR & push |
| `dependency-review.yml` | block PRs introducing high-severity vuln deps |
| `container-scan.yml` | Trivy scan of both images on PR/push, SARIF upload |
| `k8s-scan.yml` | Kubescape scan of manifests against NSA / MITRE / ArmoBest |
| `dependabot.yml` | weekly updates for pip, npm, Docker, Actions |

All workflows pin `permissions:` to least-privilege, set `persist-credentials: false` on checkout, and pin actions by version.

## 3. Application-code layer (FastAPI)

| Control | Where |
|---------|-------|
| Settings validation rejects `*` in CORS at startup | `backend/app/config/settings.py` |
| Settings validation rejects placeholder DB URLs | `backend/app/config/settings.py` |
| Webhook HMAC-SHA256 mandatory; constant-time compare; fails closed if no secret | `backend/app/api/security.py` :: `verify_github_signature` |
| API-key gate on mutating endpoints; constant-time compare; fails closed | `backend/app/api/security.py` :: `require_api_key` |
| Repo query parameter is validated against allowlist (`DORA_GITHUB_REPOS`) | `backend/app/api/routes.py` :: `_validate_repo` |
| `days` and date ranges are bounded to ≤ 730d to prevent runaway queries | `backend/app/api/routes.py` :: `_parse_range` |
| Strict CORS allowlist (no wildcard, explicit headers, scoped methods) | `backend/app/main.py` |
| Security response headers (CSP, HSTS, X-Frame-Options, …) | `backend/app/main.py` :: `SecurityHeadersMiddleware` |
| Webhook rejects events from non-allowlisted repos | `backend/app/api/routes.py` :: `github_webhook` |
| SQLAlchemy ORM (parameterized queries everywhere; no raw SQL on user input) | `backend/app/services/dora_calculator.py` etc. |
| Logs use `logger.exception` (no secret leakage in stack traces) | `backend/app/main.py` |
| ReDoc disabled; OpenAPI exposed but data-only | `backend/app/main.py` |

## 4. Container layer

| Control | Where |
|---------|-------|
| Multi-stage builds, runtime image only ships needed libs | `infra/docker/Dockerfile.backend`, `Dockerfile.frontend` |
| Non-root user (UID 10001 backend, 101 nginx) | both Dockerfiles |
| `tini` as PID 1 (signal handling, zombie reaping) | both Dockerfiles |
| HEALTHCHECK on each image | both Dockerfiles |
| nginx master runs as non-root (PID file moved to `/tmp`) | `Dockerfile.frontend` |
| nginx security headers and 1MB body cap | `infra/docker/nginx.conf` |
| `npm ci` for reproducible installs from lockfile | `Dockerfile.frontend` |
| `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges` in compose | `docker-compose.yml` |
| Secrets passed via env, never baked into image (enforced by `.dockerignore`) | `.dockerignore` |
| Compose binds ports to `127.0.0.1` only — no LAN exposure by default | `docker-compose.yml` |

## 5. Kubernetes / EKS layer

| Control | Where |
|---------|-------|
| Pod Security Standard `restricted` enforced at namespace admission | `infra/k8s/namespace.yaml` |
| `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: [ALL]`, `seccompProfile: RuntimeDefault` on every pod | `backend.yaml`, `frontend.yaml`, `postgres.yaml` |
| Resource requests AND limits on every container | all deployments |
| Liveness, readiness, startup probes on backend | `backend.yaml` |
| PodDisruptionBudget for zero-downtime drains | `backend.yaml`, `frontend.yaml` |
| Topology spread across AZs | `backend.yaml`, `frontend.yaml` |
| Default-deny NetworkPolicy + explicit allow-lists per app (⚠️ silently no-op on EKS Fargate — see [EKS-DEPLOY.md#fargate-clusters](EKS-DEPLOY.md#fargate-clusters)) | `infra/k8s/base/networkpolicy.yaml` |
| Postgres StatefulSet (gp3 PVC), only reachable from backend | `infra/k8s/overlays/trial/postgres.yaml` + NetworkPolicy |
| Dedicated ServiceAccounts; `automountServiceAccountToken: false` where unused | `serviceaccounts.yaml` |
| AWS Secrets Manager via External Secrets Operator (production) | `external-secrets.yaml` |
| Plaintext `secrets.yaml` removed from repo; only `secrets.example.yaml` shipped | `infra/k8s/secrets.example.yaml` |
| ALB Ingress: TLS 1.3, HTTPS redirect, drops invalid headers, ACM cert | `ingress.yaml` |
| Optional WAFv2 ACL annotation | `ingress.yaml` |

## 6. Operational

| Control | Recommendation |
|---------|---------------|
| GitHub PAT scope | Fine-grained, read-only, narrow to target repos |
| GitHub webhook secret rotation | quarterly via Secrets Manager versioning |
| API-key rotation | quarterly via Secrets Manager versioning, dual-deploy old/new during cutover |
| Postgres backups | RDS automated snapshots (15-min PITR), or pgBackRest if self-hosted |
| Logging | Backend uses structured stdlib logging; route to CloudWatch via Fluent Bit |
| Audit | Enable CloudTrail + EKS audit logs |
| Image provenance | Sign with cosign in CD pipeline (not yet wired in this repo) |

## 7. What's intentionally NOT included

- **mTLS between pods** — out of scope for a team-of-1 dashboard. Add Istio or Linkerd if you need it.
- **Rate limiting at the app layer** — relying on ALB / WAF rate-based rules. Add slowapi if exposing publicly without WAF.
- **Per-user auth on read endpoints** — read endpoints are intentionally public for embedding in internal dashboards. Add Cognito/OIDC if you need it.
- **Encryption-at-rest config** — assumed by EBS gp3 + RDS defaults. Verify with KMS CMK in your account.
