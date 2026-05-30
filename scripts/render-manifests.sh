#!/bin/bash
# Render infra/k8s/*.yaml templates by:
#   1. envsubst-ing $AWS_ACCOUNT_ID / $AWS_REGION / $IMAGE_TAG into build/
#   2. Failing loud if any REPLACE_* or {{...}} placeholder remains unresolved
#
# Usage:
#   AWS_ACCOUNT_ID=123 AWS_REGION=us-east-1 IMAGE_TAG=v1.0 \
#     ./scripts/render-manifests.sh

set -euo pipefail

: "${AWS_ACCOUNT_ID:?must be set}"
: "${AWS_REGION:?must be set}"
: "${IMAGE_TAG:?must be set}"

OUT_DIR="${OUT_DIR:-build/k8s}"
SRC_DIR="${SRC_DIR:-infra/k8s}"

if ! command -v envsubst >/dev/null 2>&1; then
  echo "ERROR: envsubst not found. Install with:" >&2
  echo "  macOS:  brew install gettext && brew link --force gettext" >&2
  echo "  Linux:  apt-get install -y gettext-base" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/*.yaml

for f in "$SRC_DIR"/*.yaml; do
  base=$(basename "$f")
  # Skip example file — it's a copy-template for dev secrets, not a deploy artifact.
  if [ "$base" = "secrets.example.yaml" ]; then
    continue
  fi
  envsubst < "$f" > "$OUT_DIR/$base"
done

# Fail loud on any unresolved placeholder.
unresolved=$(grep -nE 'REPLACE_|\{\{[^}]+\}\}' "$OUT_DIR"/*.yaml || true)

if [ -n "$unresolved" ]; then
  echo "ERROR: unresolved placeholders in rendered manifests:" >&2
  echo "$unresolved" >&2
  echo "" >&2
  echo "Edit the source files in $SRC_DIR/ to set real values for:" >&2
  echo "  - REPLACE_WITH_OWNER/REPO          (DORA_GITHUB_REPOS in backend.yaml)" >&2
  echo "  - REPLACE_CERT_ID                  (ACM cert ID in ingress.yaml)" >&2
  echo "  - {{REPLACE_AT_DEPLOY}}            (CD pipeline injects secret checksum)" >&2
  echo "  - dora.example.com                 (your domain in ingress.yaml)" >&2
  exit 2
fi

echo "OK: rendered $(ls "$OUT_DIR"/*.yaml | wc -l | tr -d ' ') manifests to $OUT_DIR/"
