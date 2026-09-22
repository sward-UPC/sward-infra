#!/usr/bin/env bash
# Sube las imágenes de las lambdas a ECR (Lambda no puede leer de GHCR).
# Ejecutar DESPUÉS de `cdk deploy SwardEcr` y ANTES de `cdk deploy SwardLambdas`.
#
# De dónde sale cada imagen, en este orden:
#   1. una imagen local `sward-lambda-<nombre>:local`, si existe;
#   2. el repositorio hermano `../sward-lambda-<nombre>`, construido aquí;
#   3. GHCR (`ghcr.io/sward-upc/sward-lambda-<nombre>:latest`).
# interacciones, alertas, moodle-sync y recursos son privadas en GHCR (al 22-sep):
# sin `docker login ghcr.io` solo sirven las opciones 1 y 2.
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

AQUI="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# notificaciones solo se despliega con -c notif_lambda=true, pero su repositorio
# ECR ya existe: se sube igual.
LAMBDAS=("interacciones" "alertas" "moodle-sync" "recursos" "notificaciones")

echo "→ Autenticando en ECR ($ECR_REGISTRY)..."
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

for LAMBDA in "${LAMBDAS[@]}"; do
  LOCAL_IMAGE="sward-lambda-${LAMBDA}:local"
  REPO_DIR="${AQUI}/../sward-lambda-${LAMBDA}"
  GHCR_IMAGE="ghcr.io/sward-upc/sward-lambda-${LAMBDA}:latest"
  ECR_IMAGE="${ECR_REGISTRY}/sward/lambda-${LAMBDA}:latest"

  echo ""
  if docker image inspect "$LOCAL_IMAGE" >/dev/null 2>&1; then
    echo "→ [$LAMBDA] Imagen local $LOCAL_IMAGE"
    ORIGEN="$LOCAL_IMAGE"
  elif [[ -f "$REPO_DIR/Dockerfile" ]]; then
    echo "→ [$LAMBDA] Construyendo desde $REPO_DIR..."
    # --provenance=false: Lambda rechaza los índices OCI con atestaciones.
    docker build --provenance=false -t "$LOCAL_IMAGE" "$REPO_DIR"
    ORIGEN="$LOCAL_IMAGE"
  else
    echo "→ [$LAMBDA] Pull desde GHCR..."
    docker pull "$GHCR_IMAGE"
    ORIGEN="$GHCR_IMAGE"
  fi

  docker tag "$ORIGEN" "$ECR_IMAGE"
  echo "→ [$LAMBDA] Push a ECR..."
  docker push "$ECR_IMAGE"
  echo "✓ [$LAMBDA] Listo: $ECR_IMAGE"
done

echo ""
echo "✓ Todas las imágenes lambda están en ECR."
echo "  Siguiente: cdk deploy SwardLambdas -c notif_lambda=true"
