# Security Policy

## Supported Versions

The latest `main` branch is supported. Older tagged releases are best-effort.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please report privately via GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository, or by email to the maintainer listed in `CODEOWNERS`.

Please include:

- A description of the issue and its impact
- Steps to reproduce (PoC if possible)
- Affected versions / commits
- Any suggested mitigation

You can expect an initial response within **72 hours** and a remediation plan within **7 days** for confirmed issues. We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure): please give us reasonable time to fix before public disclosure.

## Security Practices in This Repository

This project applies the following defenses (see `docs/SECURITY-HARDENING.md` for the full list):

| Layer | Control |
|-------|---------|
| **Source** | gitleaks pre-commit hook, secret scanning in CI, signed commits encouraged |
| **Dependencies** | Dependabot (weekly), `pip` hashed install in CI, `npm audit` in CI |
| **Code** | CodeQL (Python + JS), Bandit, Semgrep |
| **Container** | Non-root user, read-only root FS, distroless/alpine base, Trivy image scan |
| **K8s** | NetworkPolicy default-deny, no plaintext secrets in repo, Pod Security Standards: restricted |
| **Runtime** | Webhook HMAC verification (required, not optional), API-key auth on mutating endpoints, strict CORS allowlist |
| **TLS** | ALB Ingress with ACM, HSTS via nginx |

## Security Configuration Required Before Deploying

The repository ships with **safe defaults that refuse to start** without explicit configuration. Before running:

1. Set `DORA_GITHUB_TOKEN` (least-privilege fine-grained PAT, read-only on target repos)
2. Set `DORA_GITHUB_WEBHOOK_SECRET` (≥32 random bytes) — webhook endpoint **rejects all requests** if unset
3. Set `DORA_API_KEY` — mutating endpoints (`/collect/*`) **return 401** without it
4. Set `DORA_CORS_ORIGINS` to your frontend's exact origin(s); `*` is rejected at startup
5. Replace placeholder DB password in `infra/k8s/secrets.yaml.example` and apply via External Secrets / Secrets Manager — never commit real secrets

## Threat Model (Summary)

| Threat | Mitigation |
|--------|------------|
| Webhook spoofing | HMAC-SHA256 verification, constant-time comparison, secret required |
| Unauthenticated data ingestion | API key on `POST /collect/*` |
| Cross-origin abuse | Strict allowlist, no `*` with credentials, preflight cached |
| Secret leakage in repo | gitleaks pre-commit + CI, `.gitignore`, External Secrets in K8s |
| Supply chain | Dependabot, hashed pip installs, `npm ci`, Trivy SBOM scan |
| Container escape | Non-root UID, drop ALL caps, read-only FS, seccomp RuntimeDefault |
| Pod-to-pod lateral movement | NetworkPolicy default-deny + explicit allows |
| Token in image | `.dockerignore` excludes `.env`, multi-stage build |
| SQL injection | SQLAlchemy ORM (parameterized), no raw SQL on user input |
| DoS via large payloads | FastAPI request size limits, K8s resource limits |
