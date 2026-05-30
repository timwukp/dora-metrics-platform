# IAM policies for IRSA

These templates are referenced by `docs/EKS-DEPLOY.md` step 3.

## `dora-secrets-read.json`

Grants the backend pod read-only access to the `dora-metrics/*` secret namespace
in AWS Secrets Manager. Used by External Secrets Operator (ESO).

Substitute `${AWS_REGION}` and `${AWS_ACCOUNT_ID}` (`envsubst < dora-secrets-read.json`).

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
envsubst < infra/iam/dora-secrets-read.json > /tmp/dora-secrets-read.json
aws iam create-policy \
  --policy-name dora-secrets-read \
  --policy-document file:///tmp/dora-secrets-read.json
```

## `dora-backend-trust-policy.json`

Trust relationship for the IRSA role bound to ServiceAccount
`dora-metrics/dora-backend`. Use only if NOT using `eksctl create iamserviceaccount`
(which generates the trust policy automatically).

Find your OIDC issuer ID:

```bash
aws eks describe-cluster --name $CLUSTER \
  --query 'cluster.identity.oidc.issuer' --output text \
  | sed 's|.*/||'
```

Then:

```bash
export OIDC_ID=DB3201EC...   # output of above
envsubst < infra/iam/dora-backend-trust-policy.json > /tmp/trust.json
aws iam create-role \
  --role-name dora-backend-irsa \
  --assume-role-policy-document file:///tmp/trust.json
aws iam attach-role-policy \
  --role-name dora-backend-irsa \
  --policy-arn arn:aws:iam::$AWS_ACCOUNT_ID:policy/dora-secrets-read
```
