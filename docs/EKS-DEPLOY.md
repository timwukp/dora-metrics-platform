# EKS Deployment Runbook

## Prerequisites

- An EKS cluster (≥ 1.28) with:
  - AWS Load Balancer Controller installed
  - External Secrets Operator installed
  - A CNI that enforces NetworkPolicy (Calico, Cilium, or VPC CNI with policy enabled)
- An ACM certificate for your domain in the cluster's region
- ECR repositories: `dora-backend`, `dora-frontend`
- An IAM role for IRSA with `secretsmanager:GetSecretValue` on the secret ARN(s) used below

## 1. Build and push images

```bash
export AWS_ACCOUNT_ID=...
export AWS_REGION=us-east-1
export TAG=$(git rev-parse --short HEAD)
ECR=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR

docker build -f infra/docker/Dockerfile.backend  -t $ECR/dora-backend:$TAG .
docker build -f infra/docker/Dockerfile.frontend -t $ECR/dora-frontend:$TAG .
docker push $ECR/dora-backend:$TAG
docker push $ECR/dora-frontend:$TAG
```

## 2. Create the secret in AWS Secrets Manager

Store as a JSON map keyed by env-var name:

```bash
aws secretsmanager create-secret \
  --name dora-metrics/prod \
  --secret-string '{
    "DORA_DATABASE_URL":"postgresql://USER:PASSWORD@dora-prod.xyz.rds.amazonaws.com:5432/dora_metrics",
    "DORA_GITHUB_TOKEN":"github_pat_...",
    "DORA_GITHUB_WEBHOOK_SECRET":"<32-byte hex>",
    "DORA_API_KEY":"<random token>",
    "DORA_CLAUDE_CODE_ADMIN_KEY":"sk-ant-admin-...",
    "POSTGRES_PASSWORD":"<strong>"
  }'
```

## 3. Create the IRSA role

```bash
eksctl create iamserviceaccount \
  --cluster $CLUSTER \
  --namespace dora-metrics \
  --name dora-backend \
  --attach-policy-arn arn:aws:iam::$AWS_ACCOUNT_ID:policy/dora-secrets-read \
  --override-existing-serviceaccounts \
  --approve
```

Where `dora-secrets-read` allows `secretsmanager:GetSecretValue` on the secret ARN.

## 4. Substitute placeholders in manifests

The shipped manifests use `${VAR}` placeholders. Substitute with `envsubst`:

```bash
export AWS_ACCOUNT_ID AWS_REGION TAG
export IMAGE_TAG=$TAG
for f in infra/k8s/*.yaml; do
  envsubst < "$f" > "/tmp/$(basename $f)"
done
```

You'll also want to edit:

- `infra/k8s/ingress.yaml` — replace `dora.example.com` and the certificate ARN
- `infra/k8s/backend.yaml` — set `DORA_GITHUB_REPOS` and `DORA_CORS_ORIGINS` to your domain
- `infra/k8s/external-secrets.yaml` — set the AWS region

## 5. Apply

```bash
kubectl apply -f /tmp/namespace.yaml
kubectl apply -f /tmp/serviceaccounts.yaml
kubectl apply -f /tmp/external-secrets.yaml
# Wait for the Secret to materialize:
kubectl -n dora-metrics wait --for=condition=Ready externalsecret/dora-secrets --timeout=60s
kubectl apply -f /tmp/networkpolicy.yaml
kubectl apply -f /tmp/postgres.yaml          # OR skip + use RDS
kubectl apply -f /tmp/backend.yaml
kubectl apply -f /tmp/frontend.yaml
kubectl apply -f /tmp/ingress.yaml
```

Or with kustomize once placeholders are resolved:

```bash
kubectl apply -k infra/k8s
```

## 6. Production hardening (recommended)

| Default in manifests | Production change |
|----------------------|-------------------|
| Postgres StatefulSet | Replace with **Amazon RDS PostgreSQL** + IAM auth + Multi-AZ |
| `clusterIP` Service for backend | Add **internal NLB** if other services need direct access |
| ALB with public scheme | Add **WAFv2** ACL — uncomment annotation in `ingress.yaml` |
| Image tag `:latest` style | Tag and pin by **immutable digest** in CD pipeline |
| Logs to stdout | Ship via **Fluent Bit → CloudWatch / OpenSearch** |
| No mTLS between pods | Add **Istio** or **Linkerd** if compliance requires it |

## 7. Configure GitHub webhook (after deploy)

```bash
WEBHOOK_URL=https://dora.example.com/api/v1/webhooks/github
SECRET=$(aws secretsmanager get-secret-value --secret-id dora-metrics/prod \
  --query SecretString --output text | jq -r .DORA_GITHUB_WEBHOOK_SECRET)

gh api repos/$OWNER/$REPO/hooks --method POST -f \
  name=web \
  -f config[url]=$WEBHOOK_URL \
  -f config[content_type]=json \
  -f config[secret]=$SECRET \
  -f events[]=pull_request \
  -f events[]=workflow_run \
  -f events[]=deployment_status
```

## 8. Smoke test

```bash
curl https://dora.example.com/health
curl https://dora.example.com/api/v1/metrics/dora?days=30
```

The dashboard should be reachable at `https://dora.example.com/`.
