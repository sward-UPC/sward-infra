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

# Se construye y se sube con buildx, en un solo paso y con
# `oci-mediatypes=false`. Es obligatorio: Docker moderno (29.x) escribe por
# defecto un índice OCI —`application/vnd.oci.image.index.v1+json`— y Lambda
# solo acepta el manifiesto Docker v2. Con `docker build` + `docker push`, el
# push funciona y el rechazo aparece mucho después, al crear la función:
#   «The image manifest, config or layer media type ... is not supported»
# (pasó el 26 de septiembre de 2026 y dejó SwardLambdas en ROLLBACK).
#
# `--output type=image,push=true` necesita el driver docker-container, así que
# se crea un constructor propio. Ese driver no ve las imágenes locales del
# demonio, por eso ya no hay atajo por `sward-lambda-<nombre>:local`: cada
# imagen sale de su repositorio o de GHCR, que es además más reproducible.
if ! docker buildx inspect sward-push >/dev/null 2>&1; then
  echo "→ Creando el constructor sward-push (driver docker-container)..."
  docker buildx create --name sward-push --driver docker-container --bootstrap >/dev/null
fi

for LAMBDA in "${LAMBDAS[@]}"; do
  REPO_DIR="${AQUI}/../sward-lambda-${LAMBDA}"
  GHCR_IMAGE="ghcr.io/sward-upc/sward-lambda-${LAMBDA}:latest"
  ECR_IMAGE="${ECR_REGISTRY}/sward/lambda-${LAMBDA}:latest"
  SALIDA="type=image,name=${ECR_IMAGE},oci-mediatypes=false,push=true"

  echo ""
  if [[ -f "$REPO_DIR/Dockerfile" ]]; then
    echo "→ [$LAMBDA] Construyendo y subiendo desde $REPO_DIR..."
    docker buildx --builder sward-push build \
      --provenance=false --sbom=false --platform linux/amd64 \
      --output "$SALIDA" "$REPO_DIR"
  else
    echo "→ [$LAMBDA] Reempaquetando desde GHCR..."
    # Una sola capa FROM: no cambia el contenido, solo reescribe el manifiesto
    # en el formato que Lambda entiende.
    echo "FROM ${GHCR_IMAGE}" | docker buildx --builder sward-push build \
      --provenance=false --sbom=false --platform linux/amd64 \
      --output "$SALIDA" -f - .
  fi
  echo "✓ [$LAMBDA] Listo: $ECR_IMAGE"
done

echo ""
echo "✓ Todas las imágenes lambda están en ECR."
echo "  Siguiente: cdk deploy SwardLambdas -c notif_lambda=true"
