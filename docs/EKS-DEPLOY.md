# EKS Deployment Runbook

This guide covers two paths:

- **[Trial mode](#trial-mode-port-forward-only)** — minimal install on an existing cluster, no public exposure, port-forward access. Good for quick evaluation.
- **[Production](#production)** — full setup with RDS, IRSA, ALB+ACM, External Secrets, NetworkPolicy.

---

## Trial mode (port-forward only)

For evaluating the platform on an existing EKS cluster without provisioning an
ALB, ACM cert, or domain. Uses in-cluster Postgres.

### Prerequisites (trial)

- Existing EKS cluster (≥ 1.28) — Fargate or managed nodes both work
- ECR repos `dora-backend`, `dora-frontend` (created automatically by `scripts/build-and-push.sh`)
- `kubectl` pointed at the cluster

### Steps

```bash
# 1. Build and push images (linux/amd64 forced for Fargate compatibility)
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export TAG=$(git rev-parse --short HEAD)
./scripts/build-and-push.sh

# 2. Create namespace + secrets directly (no Secrets Manager / no ESO)
kubectl create namespace dora-metrics --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic dora-secrets -n dora-metrics \
  --from-literal=DORA_DATABASE_URL="postgresql://dora:$(openssl rand -hex 16)@postgres:5432/dora_metrics" \
  --from-literal=DORA_GITHUB_TOKEN="$DORA_GITHUB_TOKEN" \
  --from-literal=DORA_GITHUB_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=DORA_API_KEY="$(openssl rand -base64 36 | tr -d /=+)" \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 16)"

# 3. Render manifests + apply trial-mode subset (no Ingress, no ESO)
export IMAGE_TAG=$TAG
./scripts/render-manifests.sh
kubectl apply -f build/k8s/namespace.yaml
kubectl apply -f build/k8s/serviceaccounts.yaml
kubectl apply -f build/k8s/networkpolicy.yaml
kubectl apply -f build/k8s/postgres.yaml
kubectl apply -f build/k8s/backend.yaml
kubectl apply -f build/k8s/frontend.yaml
# Skip: ingress.yaml, external-secrets.yaml

# 4. Port-forward to access the dashboard locally
kubectl -n dora-metrics port-forward svc/dora-frontend 3000:80
open http://localhost:3000
```

### Trial-mode caveats

- **Webhooks won't work** without a publicly reachable URL — use a tunnel (e.g. ngrok) or skip webhook-driven flows
- **NetworkPolicy is no-op on Fargate** — see [Fargate clusters](#fargate-clusters)
- **In-cluster Postgres** has no backups, no Multi-AZ — fine for evaluation, not production
- **Apple Silicon → Fargate**: `scripts/build-and-push.sh` forces `--platform linux/amd64`. A plain `docker build` would silently produce arm64 images that fail to pull on Fargate

---

## Production

### Prerequisites (production)

| Component | How to install |
|-----------|---------------|
| EKS cluster (≥ 1.28) | `eksctl create cluster ...` |
| AWS Load Balancer Controller | `helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system --set clusterName=$CLUSTER` |
| External Secrets Operator | `helm install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace` |
| CNI with NetworkPolicy enforcement | Calico/Cilium, or VPC CNI with `enable_network_policy=true` (NOT Fargate — see below) |
| ACM certificate | `aws acm request-certificate --domain-name dora.example.com --validation-method DNS` |
| ECR repos `dora-backend`, `dora-frontend` | Created automatically by `scripts/build-and-push.sh` |

### 1. Build and push images

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
export TAG=$(git rev-parse --short HEAD)
./scripts/build-and-push.sh
```

### 2. Create the secret in AWS Secrets Manager

```bash
aws secretsmanager create-secret \
  --name dora-metrics/prod \
  --secret-string "$(jq -n \
    --arg db "$DATABASE_URL" \
    --arg gh "$GITHUB_TOKEN" \
    --arg wh "$(openssl rand -hex 32)" \
    --arg ak "$(openssl rand -base64 36 | tr -d /=+)" \
    --arg pw "$(openssl rand -hex 24)" \
    '{
      DORA_DATABASE_URL:$db,
      DORA_GITHUB_TOKEN:$gh,
      DORA_GITHUB_WEBHOOK_SECRET:$wh,
      DORA_API_KEY:$ak,
      POSTGRES_PASSWORD:$pw
    }')"
```

### 3. Create the IRSA role

The IAM policy template is provided at [`infra/iam/dora-secrets-read.json`](../infra/iam/dora-secrets-read.json):

```bash
envsubst < infra/iam/dora-secrets-read.json > /tmp/dora-secrets-read.json
aws iam create-policy \
  --policy-name dora-secrets-read \
  --policy-document file:///tmp/dora-secrets-read.json

eksctl create iamserviceaccount \
  --cluster $CLUSTER \
  --namespace dora-metrics \
  --name dora-backend \
  --attach-policy-arn arn:aws:iam::$AWS_ACCOUNT_ID:policy/dora-secrets-read \
  --override-existing-serviceaccounts \
  --approve
```

If you don't use `eksctl`, see [`infra/iam/README.md`](../infra/iam/README.md) for the manual trust-policy path.

### 4. Render manifests

The shipped manifests use `${VAR}` shell placeholders for `AWS_ACCOUNT_ID`,
`AWS_REGION`, and `IMAGE_TAG`. Use the helper script to envsubst them and
**fail loud** if any `REPLACE_*` placeholders remain unresolved:

```bash
export IMAGE_TAG=$TAG
./scripts/render-manifests.sh
```

You will be told if any of these still need editing in `infra/k8s/`:

- `REPLACE_WITH_OWNER/REPO` in `backend.yaml` (set `DORA_GITHUB_REPOS`)
- `REPLACE_CERT_ID` in `ingress.yaml` (your ACM cert ID)
- `dora.example.com` in `ingress.yaml` (your hostname)
- `{{REPLACE_AT_DEPLOY}}` in `backend.yaml` (CD pipeline injects secret checksum)

### 5. Apply

```bash
kubectl apply -f build/k8s/namespace.yaml
kubectl apply -f build/k8s/serviceaccounts.yaml
kubectl apply -f build/k8s/external-secrets.yaml
kubectl -n dora-metrics wait --for=condition=Ready externalsecret/dora-secrets --timeout=60s
kubectl apply -f build/k8s/networkpolicy.yaml
kubectl apply -f build/k8s/postgres.yaml          # OR skip + use RDS via DORA_DATABASE_URL
kubectl apply -f build/k8s/backend.yaml
kubectl apply -f build/k8s/frontend.yaml
kubectl apply -f build/k8s/ingress.yaml
```

### 6. Production hardening (recommended)

| Default in manifests | Production change |
|----------------------|-------------------|
| Postgres StatefulSet | Replace with **Amazon RDS PostgreSQL** + IAM auth + Multi-AZ |
| ALB with public scheme | Add **WAFv2** ACL — uncomment annotation in `ingress.yaml` |
| Image tag from `git rev-parse` | Pin by **immutable digest** in CD pipeline |
| Logs to stdout | Ship via **Fluent Bit → CloudWatch / OpenSearch** |
| No mTLS between pods | Add **Istio** or **Linkerd** if compliance requires it |

### 7. Configure GitHub webhook

```bash
WEBHOOK_URL=https://dora.example.com/api/v1/webhooks/github
SECRET=$(aws secretsmanager get-secret-value --secret-id dora-metrics/prod \
  --query SecretString --output text | jq -r .DORA_GITHUB_WEBHOOK_SECRET)

gh api repos/$OWNER/$REPO/hooks --method POST \
  -f name=web \
  -f config[url]=$WEBHOOK_URL \
  -f config[content_type]=json \
  -f config[secret]=$SECRET \
  -f events[]=pull_request \
  -f events[]=workflow_run \
  -f events[]=deployment_status
```

### 8. Smoke test

```bash
curl https://dora.example.com/health
curl https://dora.example.com/api/v1/metrics/dora?days=30
```

The dashboard should be reachable at `https://dora.example.com/`.

---

## Schema migrations (Alembic)

The schema is owned by Alembic. The base kustomization includes a
`dora-migrate` Job that runs `alembic upgrade head` against
`DORA_DATABASE_URL` from the `dora-secrets` Secret; the backend Deployment
is deliberately **not** ordered after the Job because both are applied in
the same overlay — the backend's lifespan refuses to start until the DB is
at head, so the rolling pods will simply CrashLoop until the Job finishes
(typically a few seconds for the initial migration).

### Trial mode

`DORA_AUTO_MIGRATE=true` is set in the trial overlay (effectively
"`alembic upgrade head` at process start"). This is fine for trial because
there is exactly one backend pod.

### Production

The migrate Job runs once per release. To re-run on every deploy, the CD
pipeline should suffix the Job name with the image tag:

```yaml
# kustomize/overlays/production/kustomization.yaml
nameSuffix: -${IMAGE_TAG}    # via render-manifests.sh
```

…or `kubectl delete job dora-migrate -n dora-metrics` before re-applying.

### Upgrading from pre-Alembic deployments

If you deployed before this change (i.e. tables were created by the old
`Base.metadata.create_all()` lifespan), `alembic upgrade head` will fail
with `DuplicateTable`. Run **once**:

```bash
kubectl -n dora-metrics exec deploy/dora-backend -- \
  alembic stamp head
```

…then redeploy normally.

---

## Fargate clusters

> ⚠️ **Security caveat:** EKS Fargate does **not** enforce NetworkPolicy.
> The shipped `default-deny-all` NetworkPolicy and per-app policies will
> apply (`kubectl apply` succeeds), but Fargate's datapath silently ignores
> them. The README's "default-deny NetworkPolicy" claim does not hold on a
> Fargate-only cluster — you have to replace it with one of the
> alternatives below.

### Why

Fargate uses its own micro-VM datapath; it doesn't run a DaemonSet-capable
CNI such as Calico/Cilium, and the in-tree VPC CNI policy mode doesn't
apply to Fargate pods either. There is currently no way to install a
NetworkPolicy enforcer on Fargate.

### Detect-and-warn

The backend reads its node name via the downward API
(`spec.nodeName` → `K8S_NODE_NAME`) at startup. Fargate-scheduled pods
always run on nodes named `fargate-…`, so the lifespan logs a loud
`WARNING` when it detects one:

```
WARNING app.main: DETECTED EKS FARGATE NODE (fargate-ip-…):
  NetworkPolicy is NOT enforced on Fargate. The shipped default-deny-all
  NetworkPolicy is a silent no-op. Use Security Groups for Pods (SGP) or
  replace Fargate with a managed node group.
  See docs/EKS-DEPLOY.md#fargate-clusters
```

You'll see this in `kubectl logs deploy/dora-backend -n dora-metrics`. If
you see it on a cluster you intended to be NetworkPolicy-enforced, treat
it as a security regression and switch to one of the options below.

### Replacements

For Fargate-only clusters, replace network isolation with **one** of:

1. **Security Groups for Pods (SGP)** — attach SGs via the
   `SecurityGroupPolicy` CRD; restrict egress at the SG level. Works on
   Fargate with the `vpc.amazonaws.com/has-trunk-attached` label.
   - <https://docs.aws.amazon.com/eks/latest/userguide/security-groups-pods.html>
2. **VPC NACLs** — restrict outbound at subnet level. Coarse-grained
   (per-subnet, not per-pod) but cheap and Fargate-compatible.
3. **Service mesh** — App Mesh, Linkerd, or Istio for east-west mTLS +
   policy. Heaviest option; only worth it if you already run a mesh.

Or use a **managed node group** (EC2-backed) instead of Fargate to keep
NetworkPolicy semantics natively. The trial-mode flow above works either
way — only the Fargate flag flips between cluster types.

### Quick check whether your cluster is Fargate-only

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.labels.eks\.amazonaws\.com/compute-type}{"\n"}{end}' | sort -u
# Output of `fargate` only → Fargate-only cluster, NetworkPolicy is NOT enforced
# Output of `ec2` (or empty) → managed node group, NetworkPolicy IS enforced if a CNI supports it
# Mixed output → check pod placement; Fargate pods skip enforcement, EC2 pods don't
```
