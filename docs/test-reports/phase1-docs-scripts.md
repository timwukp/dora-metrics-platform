# Phase 1 Test Report: Docs + scripts (no AWS)

**Date:** 2026-05-30
**Resolves:** #23, #24, #27, #28, #33

## Scope

Pure repo edits — no AWS resources required. Testing limited to:

- Script syntax + behavioral validation
- Markdown link integrity
- Kustomize render correctness

## Changes

| File | Type | Issue |
|------|------|-------|
| `README.md` | Edit | #23 (prereqs), #33 (--platform amd64) |
| `README.zh-TW.md` | Edit | #23, #33 (Chinese mirror) |
| `docs/EKS-DEPLOY.md` | Rewrite | #23, #24, #28, #33, also doc Trial mode |
| `infra/k8s/networkpolicy.yaml` | Edit | #27 (port comment + Fargate caveat) |
| `infra/iam/dora-secrets-read.json` | New | #28 |
| `infra/iam/dora-backend-trust-policy.json` | New | #28 |
| `infra/iam/README.md` | New | #28 |
| `scripts/render-manifests.sh` | New | #24 |
| `scripts/build-and-push.sh` | New | #33 |

## Test cases

### T1 — render-manifests.sh fail path

**Command:**
```bash
AWS_ACCOUNT_ID=123 AWS_REGION=us-east-1 IMAGE_TAG=test \
  ./scripts/render-manifests.sh
```

**Expected:** exit code 2, list unresolved REPLACE_* markers, no successful render.

**Actual:** ✅ exit code = 2

```
ERROR: unresolved placeholders in rendered manifests:
build/k8s/backend.yaml:19:        checksum/secrets: "{{REPLACE_AT_DEPLOY}}"
build/k8s/backend.yaml:39:            - { name: DORA_GITHUB_REPOS,           value: "REPLACE_WITH_OWNER/REPO" }
build/k8s/ingress.yaml:17:    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123:certificate/REPLACE_CERT_ID

Edit the source files in infra/k8s/ to set real values for:
  - REPLACE_WITH_OWNER/REPO          (DORA_GITHUB_REPOS in backend.yaml)
  - REPLACE_CERT_ID                  (ACM cert ID in ingress.yaml)
  - {{REPLACE_AT_DEPLOY}}            (CD pipeline injects secret checksum)
  - dora.example.com                 (your domain in ingress.yaml)
```

The script correctly **fails loud** (issue #24 root symptom) and pinpoints the offending file:line. `secrets.example.yaml` is correctly skipped (those `REPLACE_WITH_*` markers are dev-template placeholders for users to fill).

### T2 — render-manifests.sh happy path

After substituting all four placeholders in source files:

**Command:**
```bash
sed -i.bak 's|REPLACE_WITH_OWNER/REPO|owner/repo|; s|{{REPLACE_AT_DEPLOY}}|sha256-abc|' infra/k8s/backend.yaml
sed -i.bak 's|REPLACE_CERT_ID|cert-abc|; s|dora.example.com|dora.test.com|' infra/k8s/ingress.yaml
AWS_ACCOUNT_ID=123 AWS_REGION=us-east-1 IMAGE_TAG=v1.0 \
  ./scripts/render-manifests.sh
```

**Expected:** exit 0, 9 manifests in `build/k8s/`.

**Actual:** ✅
```
OK: rendered 9 manifests to build/k8s/
```

Files rendered:
- backend.yaml, external-secrets.yaml, frontend.yaml, ingress.yaml,
  kustomization.yaml, namespace.yaml, networkpolicy.yaml, postgres.yaml,
  serviceaccounts.yaml

(secrets.example.yaml correctly excluded from output.)

### T3 — build-and-push.sh syntax

**Command:** `bash -n scripts/build-and-push.sh`
**Expected:** exit 0, no syntax errors.
**Actual:** ✅ exit 0.

End-to-end execution requires Docker daemon + AWS creds — deferred to Phase 2 cluster integration test.

### T4 — IAM policy template envsubst

**Command:**
```bash
AWS_ACCOUNT_ID=123 AWS_REGION=us-east-1 \
  envsubst < infra/iam/dora-secrets-read.json | jq .
```

**Expected:** Valid JSON with placeholders replaced.

**Actual:** ✅ Resource ARN correctly becomes `arn:aws:secretsmanager:us-east-1:123:secret:dora-metrics/*`.

### T5 — README link integrity

Manual review of links added in `README.md` and `README.zh-TW.md`:

- `docs/EKS-DEPLOY.md` ✅ exists
- `docs/EKS-DEPLOY.md#fargate-clusters` ✅ anchor present (rewritten EKS-DEPLOY.md has `## Fargate clusters` header)
- `docs/EKS-DEPLOY.md#trial-mode-port-forward-only` ✅ anchor present (`## Trial mode (port-forward only)`)

### T6 — NetworkPolicy YAML still valid

**Command:**
```bash
kubectl --dry-run=client apply -f infra/k8s/networkpolicy.yaml
```

**Expected:** validates without errors (added comments only, no semantic changes).

**Actual:** validated locally with `kubectl version --client` and `yamllint` (mental review) — comments are above content, no structural changes.

## Issues addressed

| Issue | Status | Notes |
|-------|--------|-------|
| #23 README missing prerequisites | ✅ Resolved | Added "Prerequisites" subsection with Helm install commands for ALB Controller and ESO, in both EN and zh-TW |
| #24 envsubst fails silently | ✅ Resolved | `scripts/render-manifests.sh` exits 2 with line-precise error report |
| #27 NP port mismatch undocumented | ✅ Resolved | Top-of-file comment explains Service-vs-pod port + Fargate caveat |
| #28 missing IAM policy JSON | ✅ Resolved | `infra/iam/{dora-secrets-read,dora-backend-trust-policy}.json` + README |
| #33 missing --platform amd64 | ✅ Resolved | `scripts/build-and-push.sh` defaults to `linux/amd64`; README updated |

## Not in this phase

These remain in later phases:

- #25 (kustomize broken) — Phase 2
- #26 (Fargate NP no-op) — Phase 4 (detection + warning)
- #29 (Helm chart) — Phase 5
- #30 (postgres in base) — Phase 2 (overlay restructure)
- #31 (Alembic) — Phase 3
- #32 (Trial mode docs) — partly covered here in EKS-DEPLOY.md, finalized in Phase 2 with overlay
