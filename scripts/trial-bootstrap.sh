#!/bin/bash
# Bootstrap trial-mode secrets for the dora-metrics namespace.
#
# Creates:
#   - dora-metrics namespace
#   - dora-secrets Secret with all required env vars
#
# Usage:
#   DORA_GITHUB_TOKEN=ghp_xxx \
#   DORA_GITHUB_REPOS=owner/repo \
#     ./scripts/trial-bootstrap.sh
#
# Optional:
#   DORA_NAMESPACE     (default: dora-metrics)
#   DORA_DB_PASSWORD   (default: random)

set -euo pipefail

: "${DORA_GITHUB_TOKEN:?must be set}"
: "${DORA_GITHUB_REPOS:?must be set, e.g. owner/repo}"

NS="${DORA_NAMESPACE:-dora-metrics}"
DB_PW="${DORA_DB_PASSWORD:-$(openssl rand -hex 16)}"
WH_SECRET="$(openssl rand -hex 32)"
API_KEY="$(openssl rand -base64 36 | tr -d '/=+')"

echo ">> creating namespace $NS"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# PSS restricted enforcement is enabled in base/namespace.yaml — keep that.
kubectl label namespace "$NS" \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  --overwrite

echo ">> creating dora-secrets in $NS"
kubectl create secret generic dora-secrets -n "$NS" \
  --dry-run=client -o yaml \
  --from-literal=DORA_DATABASE_URL="postgresql://dora:${DB_PW}@postgres:5432/dora_metrics" \
  --from-literal=DORA_GITHUB_TOKEN="$DORA_GITHUB_TOKEN" \
  --from-literal=DORA_GITHUB_WEBHOOK_SECRET="$WH_SECRET" \
  --from-literal=DORA_API_KEY="$API_KEY" \
  --from-literal=POSTGRES_PASSWORD="$DB_PW" \
  | kubectl apply -f -

# Save the API key locally (chmod 600) so the operator can authenticate to
# protected mutating endpoints.
mkdir -p "${HOME}/.config/dora"
chmod 700 "${HOME}/.config/dora"
echo "$API_KEY" > "${HOME}/.config/dora/apikey"
chmod 600 "${HOME}/.config/dora/apikey"

echo ">> done"
echo "   API key saved to ~/.config/dora/apikey (chmod 600)"
echo "   GitHub repos: $DORA_GITHUB_REPOS"
echo "   Next: edit infra/k8s/base/backend.yaml DORA_GITHUB_REPOS env, then:"
echo "     kubectl apply -k infra/k8s/overlays/trial"
