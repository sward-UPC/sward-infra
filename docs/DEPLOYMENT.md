# DEPLOYMENT — sward-infra

Procedimiento de despliegue de la infraestructura SWARD en AWS con CDK (Python).

> El despliegue real a AWS lo ejecuta el equipo/pipeline. Este documento describe
> el orden, los prerrequisitos y cómo se construyen las imágenes. **No** ejecutes
> `cdk deploy` desde este repo de forma automática sin revisión.

---

## 1. Prerrequisitos

1. **Cuenta AWS** con permisos para crear VPC, ECS, ECR, RDS, ElastiCache,
   Secrets Manager, S3, Lambda, EventBridge, SQS, IAM y ALB.
2. **AWS CLI** configurado (`aws configure` o SSO) apuntando a la cuenta/region
   destino.
3. **Node.js 20+** y la CDK CLI: `npm install -g aws-cdk`.
4. **Python 3.11** y dependencias del repo:
   ```bash
   python3.11 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   ```
5. **Bootstrap del entorno CDK** (una sola vez por cuenta/region):
   ```bash
   cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
   ```
   Crea el bucket de assets, el repo ECR de assets y los roles `cdk-hnb659fds-*`
   que `cdk deploy` necesita.

La cuenta y region se pueden pasar por contexto (por defecto `123456789012` /
`us-east-1`):
```bash
cdk deploy --all -c account=<ACCOUNT_ID> -c region=<REGION>
```

---

## 2. Orden de despliegue

Los stacks tienen dependencias declaradas en `app.py`, así que CDK las resuelve
automáticamente. El orden efectivo es:

```
networking → ecr · secrets · storage → database · cache → services → lambdas
```

| # | Stack | Por qué este orden |
|---|---|---|
| 1 | `SwardNetworking` | La VPC la consumen database, cache y services. |
| 2 | `SwardEcr` | Los repos deben existir **y tener imágenes** antes de ECS. |
| 2 | `SwardSecrets` | Secretos referenciados por las task definitions. |
| 2 | `SwardStorage` | Buckets S3 (recursos + modelos). |
| 3 | `SwardDatabase` | RDS en la VPC; genera credenciales en Secrets Manager. |
| 3 | `SwardCache` | Redis en la VPC. |
| 4 | `SwardServices` | ECS Fargate + ALB; consume ECR, secrets, RDS y Redis. |
| 5 | `SwardLambdas` | EventBus, Lambdas, reglas EventBridge, SQS+DLQ, trigger S3. |

### Paso obligatorio entre (2) y (4): build + push de imágenes a ECR

ECS arranca tasks con la imagen `sward/<servicio>:latest`. **Si el repo ECR está
vacío, las tasks no arrancan.** Por eso, tras desplegar `SwardEcr` hay que
construir y empujar las imágenes de los 6 microservicios antes de desplegar
`SwardServices`:

```bash
ACCOUNT_ID=<ACCOUNT_ID>; REGION=<REGION>
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

for svc in usuarios integracion-lms trazabilidad cursos-recursos recomendacion xai; do
  REPO="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/sward/$svc"
  docker build -t "$REPO:latest" ../sward-ms-$svc   # Dockerfile expone 8000
  docker push "$REPO:latest"
done
```

Secuencia recomendada:
```bash
cdk deploy SwardEcr SwardSecrets SwardStorage SwardNetworking \
  SwardDatabase SwardCache            # crea repos, red, datos, cache
# ... build + push de las 6 imágenes (script de arriba) ...
cdk deploy SwardServices SwardLambdas # arranca ECS y wiring de eventos
```

O, si las imágenes ya están publicadas:
```bash
cdk deploy --all
```

---

## 3. Cómo el pipeline construye las imágenes

Cada microservicio (`sward-ms-*`) tiene su propio `Dockerfile` (expone el puerto
8000) y su pipeline de CI/CD. El flujo por microservicio:

1. CI del repo del microservicio hace build de la imagen.
2. Login a ECR (`aws ecr get-login-password | docker login ...`).
3. `docker build` + `docker push` a `sward/<servicio>` con tag `latest`
   (y opcionalmente el SHA del commit).
4. `aws ecs update-service --cluster sward-cluster --service <servicio> \
   --force-new-deployment` para que ECS tome la nueva imagen.

Las **4 Lambdas** (`sward-lambda-*`) se despliegan desde **sus propios repos con
AWS SAM** (`sam build && sam deploy`). En este stack de CDK las funciones se
declaran con un **código placeholder** únicamente para fijar la topología de
eventos (EventBridge rules, SQS+DLQ, trigger S3). El bundle real lo entrega el
pipeline SAM de cada Lambda, que actualiza el código de la función ya existente.

---

## 4. Wiring de eventos (LambdasStack)

| Disparador | Destino | Reintentos |
|---|---|---|
| EventBridge `InteraccionRegistrada` (source `sward.trazabilidad`) | SQS `sward-interacciones` → `lambda-interacciones` | DLQ `sward-interacciones-dlq`, `maxReceiveCount=3` |
| EventBridge `RecomendacionGenerada` (source `sward.recomendacion`) | `lambda-alertas` | reintentos nativos Lambda |
| Schedule `rate(15 minutes)` | `lambda-moodle-sync` | — |
| S3 `ObjectCreated` en `sward-recursos-educativos` | `lambda-recursos` | — |

---

## 5. Validación previa (sin desplegar)

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check stacks/ app.py
ruff format --check stacks/ app.py
AWS_DEFAULT_REGION=us-east-1 cdk synth   # usa cdk.context.json (AZ cacheadas)
```

`cdk synth` no requiere credenciales reales: `cdk.context.json` cachea las AZ del
entorno por defecto, igual que en el workflow de CI (`.github/workflows/ci.yml`).

---

## 6. TODO / pendientes de producción

- **HTTPS/ACM:** el listener del ALB es HTTP:80. Antes de producción, crear un
  certificado ACM, añadir un listener HTTPS:443 con `certificates=[cert]` y
  redirigir 80 → 443. (Ver `TODO(ACM)` en `stacks/services_stack.py`.)
- **Valores reales de secretos:** rellenar `sward/moodle-token` tras el deploy.
- **RDS:** `deletion_protection=False` y `removal_policy=DESTROY` son adecuados
  para sandbox; endurecer para producción.
- **Auto-scaling** de los Fargate Services según carga (no configurado aún).
