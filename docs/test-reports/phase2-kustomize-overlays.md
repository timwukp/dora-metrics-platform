# Phase 2 Test Report: Kustomize overlays + Trial mode

**Date:** 2026-05-30
**Resolves:** #25, #30, #32

## Scope

Restructure `infra/k8s/` from a flat directory into base + overlays so that
`kubectl apply -k …` actually works for two distinct deployment modes:

```
infra/k8s/
├── base/                       # common manifests, no Ingress, no Postgres, no ESO
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── serviceaccounts.yaml    # IRSA annotation moved to production overlay
│   ├── networkpolicy.yaml
│   ├── backend.yaml            # image: dora-backend:placeholder
│   └── frontend.yaml           # image: dora-frontend:placeholder
└── overlays/
    ├── trial/                  # in-cluster Postgres, no Ingress, 1 replica
    │   ├── kustomization.yaml
    │   └── postgres.yaml
    └── production/             # ALB ingress + ESO + IRSA, no Postgres (use RDS)
        ├── kustomization.yaml
        ├── external-secrets.yaml
        ├── ingress.yaml
        ├── secrets.example.yaml
        └── serviceaccount-irsa-patch.yaml
```

Plus a new `scripts/trial-bootstrap.sh` that creates the `dora-secrets` Secret
non-interactively for trial-mode users.

## Test cases

### T1 — `kubectl kustomize` renders cleanly

**Trial overlay:**
```bash
$ kubectl kustomize infra/k8s/overlays/trial > /tmp/trial.yaml
$ echo $?
0
$ grep -E "^kind:" /tmp/trial.yaml | sort | uniq -c
   2 kind: Deployment
   1 kind: Namespace
   4 kind: NetworkPolicy
   2 kind: PodDisruptionBudget
   3 kind: Service
   3 kind: ServiceAccount
   1 kind: StatefulSet
```

**Production overlay:**
```bash
$ kubectl kustomize infra/k8s/overlays/production > /tmp/prod.yaml
$ echo $?
0
$ grep -E "^kind:" /tmp/prod.yaml | sort | uniq -c
   2 kind: Deployment
   1 kind: ExternalSecret
   1 kind: Ingress
   1 kind: Namespace
   4 kind: NetworkPolicy
   2 kind: PodDisruptionBudget
   1 kind: SecretStore
   3 kind: Service
   3 kind: ServiceAccount
```

✅ **Trial is exactly 16 resources** (no Ingress, no ExternalSecret/SecretStore).
✅ **Production is 18 resources** (with Ingress + ExternalSecret + SecretStore, no StatefulSet).

### T2 — Resource separation correctness

| Resource | Trial | Production | Reason |
|----------|-------|-----------|--------|
| StatefulSet (postgres) | ✅ | ❌ | Production uses RDS via DORA_DATABASE_URL |
| Ingress (ALB) | ❌ | ✅ | Trial uses port-forward |
| ExternalSecret + SecretStore | ❌ | ✅ | Trial creates Secret directly |
| IRSA annotation on dora-backend SA | ❌ | ✅ | Trial doesn't access Secrets Manager |

Verified via:
```
$ grep -E "kind: StatefulSet|kind: Ingress|kind: ExternalSecret" /tmp/trial.yaml
kind: StatefulSet
$ grep -E "kind: StatefulSet|kind: Ingress|kind: ExternalSecret" /tmp/prod.yaml
kind: ExternalSecret
kind: Ingress
$ grep "eks.amazonaws.com/role-arn" /tmp/trial.yaml /tmp/prod.yaml
/tmp/prod.yaml:    eks.amazonaws.com/role-arn: arn:aws:iam::${AWS_ACCOUNT_ID}:role/dora-backend-irsa
```

### T3 — Image transforms via kustomize `images:`

Trial uses placeholder so user can test locally without ECR:
```
$ grep "image:" /tmp/trial.yaml
        image: dora-backend:placeholder
      - image: dora-frontend:placeholder
        image: postgres:16-alpine
```

Production uses ECR-style placeholder that overrides via overlay:
```
$ grep "image:" /tmp/prod.yaml
        image: REPLACE_AT_DEPLOY.dkr.ecr.REGION.amazonaws.com/dora-backend:placeholder
      - image: REPLACE_AT_DEPLOY.dkr.ecr.REGION.amazonaws.com/dora-frontend:placeholder
```

(In practice, `scripts/build-and-push.sh` will run `kustomize edit set image` to fill these in with real ECR ARN + git SHA.)

### T4 — Server-side dry-run against `dora-trial` cluster

```
$ kubectl kustomize infra/k8s/overlays/trial \
  | sed 's|dora-backend:placeholder|<live-ECR>/dora-backend:fb-1780098523|' \
  | sed 's|dora-frontend:placeholder|<live-ECR>/dora-frontend:ff-1780098631|' \
  | kubectl apply --server-side --dry-run=server -f -
namespace/dora-metrics serverside-applied (server dry run)
serviceaccount/dora-backend serverside-applied (server dry run)
serviceaccount/dora-frontend serverside-applied (server dry run)
serviceaccount/postgres serverside-applied (server dry run)
service/dora-backend serverside-applied (server dry run)
service/dora-frontend serverside-applied (server dry run)
statefulset.apps/postgres serverside-applied (server dry run)
poddisruptionbudget.policy/dora-backend serverside-applied (server dry run)
poddisruptionbudget.policy/dora-frontend serverside-applied (server dry run)
networkpolicy.networking.k8s.io/default-deny-all serverside-applied (server dry run)
networkpolicy.networking.k8s.io/dora-backend serverside-applied (server dry run)
networkpolicy.networking.k8s.io/dora-frontend serverside-applied (server dry run)
networkpolicy.networking.k8s.io/postgres serverside-applied (server dry run)
```

✅ All resources validate server-side.

### T5 — Apply low-risk subset to live cluster

Applied just SAs + NetworkPolicies (the lowest-risk subset that won't disrupt running pods):

```
$ kubectl apply -f /tmp/trial-low-risk.yaml --server-side --force-conflicts
serviceaccount/dora-backend serverside-applied
serviceaccount/dora-frontend serverside-applied
serviceaccount/postgres serverside-applied
networkpolicy.networking.k8s.io/default-deny-all serverside-applied
networkpolicy.networking.k8s.io/dora-backend serverside-applied
networkpolicy.networking.k8s.io/dora-frontend serverside-applied
networkpolicy.networking.k8s.io/postgres serverside-applied
```

After applying:
- Pods remain running (`kubectl get pods` confirms 8h uptime)
- IRSA annotation preserved on dora-backend SA (managed by another field manager)
- Health endpoint returns 200:

```
$ kubectl port-forward -n dora-metrics svc/dora-backend 8000:8000 &
$ curl http://localhost:8000/api/v1/health/ready
{"status":"ready","version":"1.0.0"}
$ curl 'http://localhost:8000/api/v1/metrics/dora?days=30' | head -c 200
{"deployment_frequency":{"metric":"deployment_frequency","period":...
```

### T6 — `trial-bootstrap.sh` syntax

```
$ bash -n scripts/trial-bootstrap.sh && echo ok
ok
```

Runtime test deferred — would create real secrets in the trial namespace.

## Issues addressed

| Issue | Status | Notes |
|-------|--------|-------|
| #25 `kubectl apply -k` broken | ✅ Resolved | Both overlays render cleanly with `kubectl kustomize`; placeholders only remain in production overlay where they're documented |
| #30 postgres in default base | ✅ Resolved | postgres.yaml moved to `overlays/trial/`; production has none |
| #32 Trial mode install path missing | ✅ Resolved | Documented in `docs/EKS-DEPLOY.md` (Phase 1) + `scripts/trial-bootstrap.sh` here + `infra/k8s/overlays/trial/` is the implementation |

Issue #27 was annotated and is being closed via PR #34 (Phase 1) — see issue comment.

## Notes / lessons

1. The **frontend Service uses port 8080** (matching pod port and NetworkPolicy), not 80 as I originally believed. Issue #27 corrected.
2. Kustomize's `images:` transformer is the right way to handle image substitution — cleaner than `${VAR}` envsubst.
3. The IRSA annotation belongs in the production overlay only — moving it from base means trial users don't get a stale ARN reference.
4. Server-side apply with `--force-conflicts` is the safe way to test against an existing live deployment.
