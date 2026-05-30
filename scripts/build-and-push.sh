#!/bin/bash
# Build and push backend + frontend images to ECR with the correct platform.
#
# Apple Silicon → EKS Fargate gotcha: a default `docker build` on M-series Macs
# emits arm64 (or a manifest list missing linux/amd64 in some configurations),
# so the resulting image fails to pull on Fargate with:
#   "Failed to pull image: no match for platform in manifest"
#
# This script forces linux/amd64 via buildx and pushes directly.
#
# Usage:
#   AWS_ACCOUNT_ID=123 AWS_REGION=us-east-1 TAG=$(git rev-parse --short HEAD) \
#     ./scripts/build-and-push.sh

set -euo pipefail

: "${AWS_ACCOUNT_ID:?must be set}"
: "${AWS_REGION:?must be set}"
: "${TAG:?must be set, e.g. \$(git rev-parse --short HEAD)}"

PLATFORM="${PLATFORM:-linux/amd64}"   # set to linux/amd64,linux/arm64 for multi-arch
ECR="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo ">> ECR login"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR"

echo ">> ensure ECR repos exist"
for repo in dora-backend dora-frontend; do
  aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" \
    >/dev/null 2>&1 \
    || aws ecr create-repository \
         --repository-name "$repo" \
         --region "$AWS_REGION" \
         --image-scanning-configuration scanOnPush=true \
         --image-tag-mutability IMMUTABLE \
         >/dev/null
done

echo ">> build & push backend (platform=$PLATFORM)"
docker buildx build --platform "$PLATFORM" \
  -f infra/docker/Dockerfile.backend \
  -t "$ECR/dora-backend:$TAG" --push .

echo ">> build & push frontend (platform=$PLATFORM)"
docker buildx build --platform "$PLATFORM" \
  -f infra/docker/Dockerfile.frontend \
  -t "$ECR/dora-frontend:$TAG" --push .

echo ">> done"
echo "   $ECR/dora-backend:$TAG"
echo "   $ECR/dora-frontend:$TAG"
