# Phase 4 Test Report: Fargate NetworkPolicy detection + docs

**Date:** 2026-05-30
**Resolves:** #26

## Scope

EKS Fargate does **not** enforce NetworkPolicy. The shipped
`default-deny-all` and per-app NetworkPolicies apply with `kubectl apply`
but Fargate's datapath silently ignores them — making the README's
"default-deny NetworkPolicy" claim a **silent security regression** on
Fargate-only clusters.

This phase:

1. Adds a startup detect-and-warn in the backend (`_warn_if_fargate()`),
   gated on the `K8S_NODE_NAME` downward API env var.
2. Wires the env var into `infra/k8s/base/backend.yaml`.
3. Expands `docs/EKS-DEPLOY.md#fargate-clusters` with the warning's text,
   replacement options (SGP / NACL / mesh / managed node group), and a
   one-liner to detect Fargate-only clusters from outside.
4. Adds the caveat to `docs/SECURITY-HARDENING.md` so the controls table
   doesn't lie about NetworkPolicy enforcement.

## Detection signal

Fargate-scheduled pods always run on nodes named `fargate-…` (verified
across the `dora-trial` cluster's three Fargate nodes). The downward API
exposes `spec.nodeName` as `K8S_NODE_NAME`; the lifespan checks the
prefix and logs at WARN level.

```python
def _warn_if_fargate() -> None:
    node = os.environ.get("K8S_NODE_NAME", "")
    if node.startswith("fargate-"):
        logger.warning(
            "DETECTED EKS FARGATE NODE (%s): NetworkPolicy is NOT enforced "
            "on Fargate. The shipped default-deny-all NetworkPolicy is a "
            "silent no-op. Use Security Groups for Pods (SGP) or replace "
            "Fargate with a managed node group. See "
            "docs/EKS-DEPLOY.md#fargate-clusters",
            node,
        )
```

This is intentionally **not** a hard error — operators using Fargate with
SGP have a valid setup, and we don't want to refuse to start. A loud WARN
is the right escalation.

## Test cases

### T1 — Fargate node name → warning fires

```bash
$ K8S_NODE_NAME="fargate-ip-192-168-92-213.ec2.internal" \
    python -c "from app.main import _warn_if_fargate; _warn_if_fargate()"
WARNING app.main: DETECTED EKS FARGATE NODE (fargate-ip-…):
  NetworkPolicy is NOT enforced on Fargate. The shipped default-deny-all
  NetworkPolicy is a silent no-op. Use Security Groups for Pods (SGP) or
  replace Fargate with a managed node group. See
  docs/EKS-DEPLOY.md#fargate-clusters
```

✅ Warning fires.

### T2 — EC2 node name → no warning

```bash
$ K8S_NODE_NAME="ip-10-0-1-23.us-east-1.compute.internal" \
    python -c "from app.main import _warn_if_fargate; _warn_if_fargate(); print('done')"
done
```

✅ No false positive on EC2-backed nodes.

### T3 — Empty K8S_NODE_NAME → no warning

```bash
$ python -c "from app.main import _warn_if_fargate; _warn_if_fargate(); print('done')"
done
```

✅ Missing env var is graceful (e.g., local dev outside k8s).

### T4 — Downward API wiring on `dora-trial`

Patched the live backend Deployment to add the new env var (zero-risk
patch — adds env, doesn't change the image):

```bash
$ kubectl -n dora-metrics patch deployment dora-backend --type=json -p='[
    {"op":"add","path":"/spec/template/spec/containers/0/env/-",
     "value":{"name":"K8S_NODE_NAME",
              "valueFrom":{"fieldRef":{"fieldPath":"spec.nodeName"}}}}]'
deployment.apps/dora-backend patched

$ kubectl -n dora-metrics rollout status deployment/dora-backend
deployment "dora-backend" successfully rolled out

$ kubectl -n dora-metrics exec deploy/dora-backend -- printenv K8S_NODE_NAME
fargate-ip-192-168-101-132.ec2.internal
```

✅ Downward API populates `K8S_NODE_NAME` correctly. Once the new image
ships, the warning will fire on every backend pod startup in this
cluster.

### T5 — `kubectl kustomize` still renders

```bash
$ kubectl kustomize infra/k8s/overlays/trial > /tmp/t.yaml; echo $?
0
$ kubectl kustomize infra/k8s/overlays/production > /tmp/p.yaml; echo $?
0
$ grep -A3 "K8S_NODE_NAME" /tmp/t.yaml | head -5
        - name: K8S_NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
```

✅ Both overlays render with the downward API field.

### T6 — Detect Fargate-only cluster from outside

The doc adds a one-liner the operator can run:

```bash
$ kubectl get nodes \
    -o jsonpath='{range .items[*]}{.metadata.labels.eks\.amazonaws\.com/compute-type}{"\n"}{end}' \
  | sort -u
fargate
```

✅ Confirms `dora-trial` is Fargate-only — exactly the case the warning
targets.

## Issues addressed

| Issue | Status | Notes |
|-------|--------|-------|
| #26 NetworkPolicy silently no-op on Fargate | ✅ Resolved | Detect-and-warn at startup; expanded EKS-DEPLOY.md and SECURITY-HARDENING.md to call out the caveat and list replacements (SGP / NACL / mesh / managed node group) |

## Notes / lessons

1. **Why a WARN, not an error:** operators may legitimately run Fargate
   with SGP for network isolation; refusing to start would block them.
   A loud, scannable WARN with a doc link is the right signal.
2. **Why downward API instead of cloud-metadata API:** EKS pods can
   reach IMDS, but the call adds latency at startup and Fargate IMDS
   exposes different fields than EC2. The node name prefix is the
   simplest stable signal and works without the AWS SDK.
3. **No Fargate overlay added** (issue #26 listed it as "optional"). SGP
   manifests are deployment-specific (account ID, SG IDs) — adding a
   half-templated overlay would be more confusing than helpful. Doc
   pointers cover the use case.
