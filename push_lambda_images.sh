#!/usr/bin/env bash
# Retaguea las imágenes lambda de GHCR → ECR.
# Ejecutar DESPUÉS de `cdk deploy SwardEcr` y ANTES de `cdk deploy SwardLambdas`.
#
# Uso:
#   ./push_lambda_images.sh
#   ./push_lambda_images.sh --region eu-west-1   # otra región

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) AWS_REGION="$2"; shift 2 ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
done

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

LAMBDAS=("interacciones" "alertas" "moodle-sync" "recursos")

echo "→ Autenticando en ECR ($ECR_REGISTRY)..."
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

for LAMBDA in "${LAMBDAS[@]}"; do
  GHCR_IMAGE="ghcr.io/sward-upc/sward-lambda-${LAMBDA}:latest"
  ECR_IMAGE="${ECR_REGISTRY}/sward/lambda-${LAMBDA}:latest"

  echo ""
  echo "→ [$LAMBDA] Pull desde GHCR..."
  docker pull "$GHCR_IMAGE"

  echo "→ [$LAMBDA] Retag → ECR..."
  docker tag "$GHCR_IMAGE" "$ECR_IMAGE"

  echo "→ [$LAMBDA] Push a ECR..."
  docker push "$ECR_IMAGE"

  echo "✓ [$LAMBDA] Listo: $ECR_IMAGE"
done

echo ""
echo "✓ Todas las imágenes lambda están en ECR."
echo "  Ahora puedes ejecutar: cdk deploy --all --require-approval never"
