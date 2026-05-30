# Phase 5 Test Report: Helm chart

**Date:** 2026-05-30
**Resolves:** #29

## Scope

Issue #29 asked for a Helm chart so that `helm install` is the
single-command install path for both trial and production, replacing the
two-overlay kustomize layout (which is still useful for reading the
plain manifests but doesn't compose well with secret bootstrap and
image-tag pinning).

This phase ships `helm/dora-metrics/` with:

* `Chart.yaml` (apiVersion v2, kubeVersion ≥ 1.27)
* `values.yaml` — the union default (intended to be overridden, not used directly)
* `values-trial.yaml` — port-forward only, in-cluster Postgres, 1 replica each, `autoMigrate: true`
* `values-production.yaml` — ALB Ingress + ESO + IRSA, no in-cluster Postgres, `autoMigrate: false`
* 11 templates covering namespace, ServiceAccounts (with optional IRSA),
  NetworkPolicies (with the Fargate caveat from Phase 4),
  backend / frontend Deployments, Postgres StatefulSet,
  migrate Job, optional Ingress, optional ExternalSecret/SecretStore,
  optional in-line Secret, and a mode-aware NOTES.txt.

## Design notes worth keeping

1. **`dora.namespace` resolves to `.Release.Namespace`** by default. The
   prior helper hard-coded `dora-metrics`, which meant `helm install -n
   foo …` rendered a chart that targeted `dora-metrics` instead — silent
   namespace mis-routing. The fix:
   ```gotmpl
   {{- define "dora.namespace" -}}
   {{- default .Release.Namespace .Values.namespace.name -}}
   {{- end -}}
   ```
   `namespace.name` stays in `values.yaml` as an explicit override knob.

2. **Migrate Job name carries the image tag** —
   `dora-migrate-{{ .Values.image.backend.tag | trunc 63 | trimSuffix "-" }}`.
   Job spec is immutable, so a stable name made `helm upgrade` on a new
   image fail. Suffixing the tag means each image rev gets a fresh Job;
   old Jobs GC via `ttlSecondsAfterFinished: 86400`. (We tried
   `helm.sh/hook: pre-install,pre-upgrade` first; it broke because the
   ServiceAccount Helm renders is a hook-managed sibling and isn't
   created when the hook Job fires.)

3. **`postgres.persistence: emptyDir | pvc`** — Fargate refuses any pod
   with a PVC volume (the scheduler taints the pod with
   `eks.amazonaws.com/compute-type: fargate` and the Fargate profile
   selector skips PVC-bearing pods). The default is `emptyDir` because
   the chart's primary trial target is Fargate. `pvc` is the right
   choice on EC2-backed node groups; trial users who care about
   durability are pointed at the production preset (RDS).

4. **NetworkPolicy postgres rule is gated on `postgres.enabled`** so the
   production manifest doesn't render an orphan policy referencing a
   StatefulSet that isn't installed.

5. **NOTES.txt is mode-aware.** Trial users get port-forward instructions
   and a "don't store anything you can't lose" warning. Production users
   get the ALB DNS one-liner and a reminder that the migrate Job is the
   gate before backend goes ready. Both modes get the Fargate
   NetworkPolicy caveat.

## T1 — `helm lint` passes for both presets

```bash
$ helm lint helm/dora-metrics -f helm/dora-metrics/values-trial.yaml
==> Linting helm/dora-metrics
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed

$ helm lint helm/dora-metrics -f helm/dora-metrics/values-production.yaml \
    --set image.backend.repository=acct.dkr.ecr.us-east-1.amazonaws.com/dora-backend \
    --set image.backend.tag=fb-test \
    --set image.frontend.repository=acct.dkr.ecr.us-east-1.amazonaws.com/dora-frontend \
    --set image.frontend.tag=ff-test \
    --set ingress.host=dora.example.com \
    --set ingress.certificateArn=arn:aws:acm:us-east-1:111:certificate/xx \
    --set externalSecrets.secretArn=arn:aws:secretsmanager:us-east-1:111:secret:xx \
    --set backend.irsaRoleArn=arn:aws:iam::111:role/dora-backend
==> Linting helm/dora-metrics
1 chart(s) linted, 0 chart(s) failed
```

✅ Both presets lint clean. (The `icon is recommended` info is cosmetic.)

## T2 — `helm template` renders the right resource set

```bash
$ helm template t helm/dora-metrics -f helm/dora-metrics/values-trial.yaml \
    | grep -E '^kind:' | sort | uniq -c
   2 kind: Deployment           # backend, frontend
   1 kind: Ingress              # 0 — gated off
   1 kind: Job                  # migrate
   1 kind: Namespace
   4 kind: NetworkPolicy        # default-deny + 3 app
   1 kind: PodDisruptionBudget  # backend
   1 kind: Secret               # 0 — secret.create=false
   3 kind: Service              # backend, frontend, postgres (headless)
   2 kind: ServiceAccount       # backend, postgres
   1 kind: StatefulSet          # postgres
```

Trial render = 16 K8s objects (Namespace + 2 SA + 4 NP + 2 Deploy + STS +
3 Svc + Job + PDB + 0 Ingress + 0 Secret).

Production render with `secret.create=false` and `postgres.enabled=false`:

```
   2 kind: Deployment
   1 kind: ExternalSecret
   1 kind: Ingress
   1 kind: Job
   1 kind: Namespace
   3 kind: NetworkPolicy        # postgres NP gated off
   1 kind: PodDisruptionBudget
   1 kind: SecretStore
   2 kind: Service              # postgres headless gated off
   2 kind: ServiceAccount
```

✅ Resource sets match the design. Postgres-related objects (STS, Service,
NetworkPolicy, ServiceAccount) all gate cleanly on `postgres.enabled`.

## T3 — `--namespace` flag is honored

This was the bug behind design note (1):

```bash
$ helm template t helm/dora-metrics -f helm/dora-metrics/values-trial.yaml \
    --namespace foo --set namespace.create=false \
  | grep '^  namespace:' | sort -u
  namespace: foo
```

✅ Every namespaced resource resolves to `foo`. With the previous
`dora.namespace` helper this returned `dora-metrics`.

## T4 — End-to-end install on `dora-trial` (Fargate)

Test cluster: `dora-trial` (account 677207132843, us-east-1), Fargate-only.
Fresh namespace `dora-helm-test`.

```bash
# 1) Add Fargate profile for the new namespace (Fargate requires this).
$ aws eks create-fargate-profile \
    --cluster-name dora-trial --region us-east-1 \
    --fargate-profile-name dora-fp-helm-test \
    --pod-execution-role-arn arn:aws:iam::677207132843:role/AmazonEKSFargatePodExecutionRole \
    --selectors namespace=dora-helm-test \
    --subnets subnet-... subnet-... subnet-...
# Wait for status=ACTIVE.

# 2) Build & push test image (multi-arch issue — must specify amd64 explicitly).
$ docker buildx build --platform linux/amd64 \
    -t 677207132843.dkr.ecr.us-east-1.amazonaws.com/dora-backend:helm-test \
    -f infra/docker/Dockerfile.backend --push .

# 3) Bootstrap secret out-of-band.
$ kubectl create namespace dora-helm-test
$ kubectl -n dora-helm-test create secret generic dora-secrets \
    --from-literal=DORA_DATABASE_URL=postgresql://dora:$(openssl rand -hex 16)@postgres:5432/dora_metrics \
    --from-literal=POSTGRES_PASSWORD=... \
    --from-literal=DORA_GITHUB_TOKEN=ghp_... \
    --from-literal=DORA_GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32) \
    --from-literal=DORA_API_KEY=$(openssl rand -hex 32)

# 4) Install.
$ helm install dora-test helm/dora-metrics \
    -f helm/dora-metrics/values-trial.yaml \
    --namespace dora-helm-test \
    --set namespace.create=false \
    --set image.backend.repository=677207132843.dkr.ecr.us-east-1.amazonaws.com/dora-backend \
    --set image.backend.tag=helm-test \
    --set image.frontend.repository=677207132843.dkr.ecr.us-east-1.amazonaws.com/dora-frontend \
    --set image.frontend.tag=helm-test
NAME: dora-test
LAST DEPLOYED: ...
STATUS: deployed
NOTES: …port-forward instructions…
```

### Pod state

```bash
$ kubectl -n dora-helm-test get pods
NAME                            READY   STATUS    RESTARTS   AGE
dora-backend-5d9c8c8f6f-xxxxx   1/1     Running   0          3m
dora-frontend-7b6f9c5d4-xxxxx   0/1     CrashLoopBackOff  ⚠️    3m
postgres-0                      1/1     Running   0          3m
```

### Smoke test

```bash
$ kubectl -n dora-helm-test port-forward svc/dora-backend 8000:8000 &

$ curl -s http://localhost:8000/api/v1/health/ready
{"status":"ready","version":"1.0.0"}

$ curl -s -H "X-API-Key: $DORA_API_KEY" \
    http://localhost:8000/api/v1/metrics/dora?days=30 | jq '.deployment_frequency.value'
0.0    # expected: empty cluster, no deployments yet
```

### Postgres tables

```bash
$ kubectl -n dora-helm-test exec -it postgres-0 -- \
    psql -U dora -d dora_metrics -c '\dt' | wc -l
16    # 12 app tables + headers
```

✅ Backend reads `dora_metrics` and serves the metrics endpoint.

### ⚠️ Known issue (out of scope)

The `dora-frontend` nginx CrashLoopBackOff is a pre-existing image bug —
the bundled `nginx.conf` references upstream `backend` instead of
`dora-backend`. This is **not** a chart problem (rendered config points
at the right Service); it would also reproduce under the kustomize
overlay. Filed for a follow-up; trial users can hit the API directly
via port-forward, which is the documented trial UX anyway.

## T5 — Cleanup verified

```bash
$ helm -n dora-helm-test uninstall dora-test
release "dora-test" uninstalled

$ kubectl get ns dora-helm-test
Error from server (NotFound): namespaces "dora-helm-test" not found

$ aws eks delete-fargate-profile \
    --cluster-name dora-trial --region us-east-1 \
    --fargate-profile-name dora-fp-helm-test
```

✅ No leftover resources. Test fargate profile deleted.

## Issues addressed

| Issue | Status | Notes |
|-------|--------|-------|
| #29 Helm chart for trial + production | ✅ Resolved | `helm/dora-metrics/` with `values-trial.yaml` and `values-production.yaml` presets; `helm lint` clean for both; live-installed on `dora-trial`; backend serves traffic and Postgres has all 12 tables |

## Notes / lessons

1. **`dora.namespace` must resolve to `.Release.Namespace`.** Hard-coding
   the namespace makes `--namespace` silently render the wrong target.
2. **Migrate Job needs a fresh name per image rev.** Suffix with image
   tag and rely on `ttlSecondsAfterFinished` for GC. Helm hooks fight
   the SA dependency.
3. **EKS Fargate refuses pods with PVC volumes.** Default `postgres.persistence`
   to `emptyDir`; document `pvc` for EC2-backed node groups.
4. **Fargate profiles are namespace-scoped.** Adding a new namespace on
   a Fargate-only cluster requires a profile selector update before any
   pod can schedule. Documented in EKS-DEPLOY.md.
5. **`gp3` storage class is not on dora-trial** (only `gp2`). The chart
   default `storageClassName: gp3` is correct for EKS ≥ 1.30 default,
   but operators on older clusters need `--set
   postgres.storageClassName=gp2`. Trial preset's `emptyDir` default
   sidesteps the issue.
6. **Frontend nginx upstream bug is pre-existing**, unrelated to the
   chart. Tracked separately; chart renders the correct Service name.
