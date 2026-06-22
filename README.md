# sward-infra

Infraestructura como código (IaC) del sistema **SWARD** — plataforma de aprendizaje
adaptativo para estudiantes universitarios de Lima Metropolitana.

Implementado con **AWS CDK v2 (Python 3.11)**. Define toda la nube del proyecto:
red, contenedores ECS, bases de datos, secretos, almacenamiento, funciones Lambda
event-driven y la distribución CloudFront que expone el API por HTTPS.

[![CI](https://github.com/sward-UPC/sward-infra/actions/workflows/ci.yml/badge.svg)](https://github.com/sward-UPC/sward-infra/actions/workflows/ci.yml)

---

## Índice

- [Qué despliega](#qué-despliega)
- [Routing del ALB](#routing-del-alb)
- [Lambdas y eventos](#lambdas-y-eventos)
- [Cómo desplegar](#cómo-desplegar)
- [Modo dev vs prod (`is_dev`)](#modo-dev-vs-prod-is_dev)
- [Encender y apagar](#encender-y-apagar-startyml--stopyml)
- [Secrets generados e inyección a ECS](#secrets-generados-e-inyección-a-ecs)
- [Setup local](#setup-local)
- [Documentación relacionada](#documentación-relacionada)

---

## Qué despliega

La app (`app.py`) sintetiza **8 stacks** con dependencias explícitas. Cada stack
tiene una responsabilidad acotada:

| Stack | ID CDK | Rol |
|---|---|---|
| `NetworkingStack` | `SwardNetworking` | VPC de 2 AZ con subnets pública / privada-con-egress / aislada. Usa un **NAT Instance** `t3.nano` (en lugar de NAT Gateway) para abaratar el egress de las subnets privadas. |
| `EcrStack` | `SwardEcr` | Repositorios ECR `sward/lambda-<nombre>` para las **imágenes de las Lambdas** (Lambda no admite registries externos). Lifecycle policy: conserva las últimas 10 imágenes. Los microservicios ECS **no** usan ECR: tiran sus imágenes de GHCR (público). |
| `SecretsStack` | `SwardSecrets` | Secretos en **AWS Secrets Manager**: `SECRET_KEY` (JWT), una `SERVICE_KEY` por microservicio (auth service-to-service), token de Moodle, YouTube API key, y password del admin inicial. Ver [Secrets generados](#secrets-generados-e-inyección-a-ecs). |
| `StorageStack` | `SwardStorage` | Buckets S3 `sward-recursos-educativos` (material) y `sward-models` (modelos SAKT). Versionados, sin acceso público, `RemovalPolicy.RETAIN`. |
| `DatabaseStack` | `SwardDatabase` | RDS PostgreSQL 15 (`t3.micro`) en subnets aisladas. En **dev** una sola instancia compartida; en **prod** una por microservicio (6 en total). Credenciales autogeneradas en Secrets Manager. |
| `ServicesStack` | `SwardServices` | ECS Cluster + **6 Fargate services** (uno por microservicio) + ALB con path-based routing + Cloud Map (`sward.local`) para descubrimiento s2s interno. Incluye además un servicio **Redis** en Fargate (`redis.sward.local:6379`) que reemplaza a ElastiCache para ahorrar costo. |
| `LambdasStack` | `SwardLambdas` | EventBus `sward-event-bus` + Lambdas de imagen + reglas EventBridge + colas SQS con DLQ. Es el corazón event-driven del sistema. |
| `CloudfrontStack` | `SwardCloudfront` | Distribución CloudFront delante del ALB: aporta **HTTPS sin dominio propio** y resuelve CORS con dos CloudFront Functions (reescribe `/api/v1/*` → `/*` y maneja preflights en el edge). Exporta la URL pública como output `SwardApiUrl`. |

### Orden de dependencias

```
SwardNetworking
    ├── SwardDatabase
    └── SwardServices ← SwardEcr · SwardSecrets · SwardDatabase · SwardStorage
            └── SwardLambdas ← SwardStorage (S3 notifica a lambda-recursos)
                    └── SwardCloudfront ← SwardServices (ALB origin)
```

> **Nota sobre Redis.** El repo incluye `stacks/cache_stack.py` (ElastiCache Redis),
> pero **no está cableado en `app.py`**: Redis corre hoy como un contenedor Fargate
> dentro de `ServicesStack` (se apaga junto con ECS y cuesta $0 cuando está
> detenido). El stack de cache se conserva como alternativa si se requiere un Redis
> gestionado.

---

## Routing del ALB

Tráfico externo (clientes) entra por el ALB con path-based routing. El tráfico
interno entre microservicios usa Cloud Map (DNS privado `<servicio>.sward.local:8000`).

| Path(s) | Microservicio | Prioridad |
|---|---|---|
| `/auth*` `/users*` `/admin*` `/notifications*` | usuarios | 10 |
| `/lms*` | integracion-lms | 20 |
| `/interactions*` `/students*` `/dashboard*` | trazabilidad | 30 |
| `/courses*` `/resources*` | cursos-recursos | 40 |
| `/recommendations*` | recomendacion | 50 |
| `/xai*` | xai | 60 |

Health check del ALB: `GET /health` (HTTP 200). El listener es **HTTP:80**
(el HTTPS lo provee CloudFront por delante; hay un `TODO` para ACM/443 directo en el ALB).

---

## Lambdas y eventos

Las Lambdas se despliegan como **imágenes de contenedor** desde ECR.

| Función | Trigger | Acción |
|---|---|---|
| `sward-lambda-interacciones` | SQS (alimentada por EventBridge) | Normaliza `InteraccionRegistrada` hacia la BD de trazabilidad. |
| `sward-lambda-alertas` | EventBridge (`RecomendacionGenerada`, `RiesgoActualizado`) | Evalúa riesgo académico y publica `AlertaCreada`. |
| `sward-lambda-moodle-sync` | Schedule (cada 15 min) | Sincroniza datos desde Moodle vía `ms-integracion-lms`. |
| `sward-lambda-recursos` | S3 `ObjectCreated` en `sward-recursos-educativos` | Actualiza la metadata del recurso en la BD de cursos-recursos. |
| `sward-lambda-notificaciones` | SQS (feedback, logros, registro, alertas) | Crea notificaciones para estudiantes / docentes / admins. **Opcional**: solo se crea con el context flag `notif_lambda=true` (ya activado en `cdk.json`) y requiere que la imagen exista en ECR. |

Las reglas EventBridge usan `Source` = nombre del servicio y `DetailType` = tipo de
evento completo (ej. `sward.trazabilidad.InteraccionRegistrada`), coincidiendo con lo
que publica `sward_shared`.

---

## Cómo desplegar

### Vía GitHub Actions (recomendado)

El despliegue se dispara con un **push a la rama `deploy`** (o manualmente con
*workflow_dispatch*), definido en `.github/workflows/deploy.yml`:

1. **CDK Diff (preview)** — `cdk synth` + `cdk diff --all` para ver qué cambiaría.
2. **⏸ Aprobación manual** — GitHub Environment `production` pausa el pipeline.
3. **CDK Deploy** — `cdk deploy --all --require-approval never`.

El flag de modo se elige en el dispatch (`dev` por defecto / `prod`); en modo prod
se inyecta `-c prod=true`.

La rama `main` sólo corre **CI** (`.github/workflows/ci.yml`): `ruff` lint+format,
`cdk synth` en dev y prod, y `cdk diff`. No despliega.

### Manual (local)

```bash
# Modo dev (por defecto)
cdk deploy --all --require-approval never

# Modo prod (6 RDS aisladas, Fargate on-demand)
cdk deploy --all --require-approval never -c prod=true
```

> **Imágenes de las Lambdas.** El primer despliegue crea los repos ECR vacíos. Antes
> de poder crear las funciones hay que subir las imágenes:
> `cdk deploy SwardEcr` → `./push_lambda_images.sh` (retaguea de GHCR a ECR) →
> `cdk deploy --all`. El detalle está en [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

---

## Modo dev vs prod (`is_dev`)

El modo lo controla **un único flag** en `app.py`:

```python
is_dev = app.node.try_get_context("prod") != "true"
```

Es decir: **dev es el modo por defecto**; se entra a prod sólo con `-c prod=true`.
`is_dev` se propaga a `DatabaseStack`, `ServicesStack` y `LambdasStack`.

| Aspecto | Dev (`is_dev=True`, por defecto) | Prod (`-c prod=true`) |
|---|---|---|
| RDS | 1 instancia `t3.micro` **compartida** (BD `sward`) | 1 instancia `t3.micro` **por microservicio** (`sward_<servicio>`) |
| Capacidad ECS | **Fargate Spot** (~40% del precio on-demand) | Fargate on-demand |
| `DATABASE_NAME` inyectado | `sward` para todos | `sward_<servicio>` por servicio |
| Costo aproximado corriendo | ~$50/mes | mayor (6 RDS + on-demand) |

En dev cada microservicio crea sus propias tablas sobre la BD compartida (vía
`create_all()` de SQLAlchemy), por lo que conviven en una sola instancia.

---

## Encender y apagar (`start.yml` / `stop.yml`)

Para no pagar 24/7, la infra se **enciende y apaga** con dos workflows
(`workflow_dispatch` manual). El apagado además corre en **schedule diario** a las
00:00 hora Perú (`cron: "0 5 * * *"`).

| Workflow | Acción |
|---|---|
| `.github/workflows/start.yml` | Inicia las instancias RDS `sward*` y espera a que estén `available`; escala todos los servicios ECS (incl. `redis`) a `desired-count=1`; elimina el límite de concurrencia reservada de las Lambdas. |
| `.github/workflows/stop.yml` | Escala los servicios ECS a `desired-count=0`; detiene las instancias RDS; pone las Lambdas en `reserved-concurrency=0`. |

Apagar **no destruye** nada: conserva datos y configuración. Para destruir todo de
forma irreversible existe `.github/workflows/destroy.yml` (requiere escribir
`DESTRUIR` para confirmar; corre `cdk destroy --all`).

> Hay equivalentes manuales por CLI documentados en [`docs/ON_OFF.md`](docs/ON_OFF.md).

---

## Secrets generados e inyección a ECS

`SecretsStack` crea estos secretos en **AWS Secrets Manager** (todos con
`RemovalPolicy.DESTROY`). Los marcados como *placeholder* se generan con un valor
aleatorio y deben rellenarse manualmente tras el deploy.

| Secret (Secrets Manager) | Clave(s) JSON | Generado por | Uso |
|---|---|---|---|
| `sward/jwt-secret` | `secret_key`, `jwt_algorithm` | `SecretsStack` (random 64) | `SECRET_KEY` compartida para firmar/validar JWT (HS256). |
| `sward/service-key/<servicio>` | `service_key` | `SecretsStack` (random 48) | `SERVICE_KEY` por microservicio para auth service-to-service. |
| `sward/moodle-token` | `moodle_token`, `moodle_base_url` | `SecretsStack` (placeholder) | Token y URL base de la API de Moodle (`ms-integracion-lms`). **Rellenar manual.** |
| `sward/youtube-api-key` | `youtube_api_key` | `SecretsStack` (placeholder) | YouTube Data API v3 para el material generado (`ms-recomendacion`). **Best-effort.** |
| `sward/admin-seed` | `admin_seed_password` | `SecretsStack` (placeholder) | Password del admin inicial (`ms-usuarios`). **Rellenar manual.** |
| `sward/rds/<servicio>` (o `sward/rds/shared` en dev) | `username`, `password`, ... | `DatabaseStack` (RDS autogenera) | Credenciales de la instancia RDS correspondiente. |

### Cómo llegan a los contenedores ECS

`ServicesStack` distingue dos canales en cada task definition:

- **Variables de entorno en claro** (no sensibles): `ENVIRONMENT`, `AWS_REGION`,
  `EVENTBRIDGE_BUS_NAME`, `CORS_ALLOWED_ORIGINS`, `DATABASE_HOST/PORT/NAME`,
  las `*_SERVICE_URL` (Cloud Map), `REDIS_URL`, flags como `MOODLE_MOCK` o
  `USE_MOCK_LMS`, etc.
- **`secrets` desde Secrets Manager** (cifrados, resueltos por ECS al arrancar el
  container) usando `ecs.Secret.from_secrets_manager(...)`:
  - `DB_USERNAME` / `DB_PASSWORD` ← `sward/rds/...`
  - `SECRET_KEY` ← `sward/jwt-secret`
  - `SERVICE_KEY` ← `sward/service-key/<servicio>` (y `LMS_SERVICE_KEY` en usuarios)
  - `MOODLE_TOKEN` / `MOODLE_BASE_URL` ← `sward/moodle-token` (solo integracion-lms)
  - `ADMIN_SEED_PASSWORD` ← `sward/admin-seed` (solo usuarios)
  - `YOUTUBE_API_KEY` ← `sward/youtube-api-key` (solo recomendacion)
  - `AUTHORIZED_<CALLER>_KEY` ← la `SERVICE_KEY` de cada caller autorizado, para
    validar el header `X-Service-Key` en las llamadas s2s entrantes.

La aplicación compone la `DATABASE_URL` a partir de `DB_USERNAME`, `DB_PASSWORD` y
los componentes `DATABASE_HOST/PORT/NAME`. Ningún secreto se hardcodea ni viaja como
variable de entorno en texto plano.

> **Reconstrucción de la infra.** Como varios secretos se **regeneran aleatoriamente**
> en cada despliegue limpio, los GitHub Secrets de los repos que los consumen deben
> re-sincronizarse. El procedimiento (qué secret va en qué repo, en qué orden, cómo
> obtener cada valor) está en el **runbook de github-secrets en `sward-docs`**:
> [`sward-docs/github-secrets-runbook.md`](../sward-docs/github-secrets-runbook.md).

---

## Setup local

```bash
# 1. Entorno virtual
python -m venv .venv && source .venv/bin/activate

# 2. Dependencias
pip install -r requirements.txt -r requirements-dev.txt

# 3. Bootstrap CDK (solo la primera vez por cuenta/región)
cdk bootstrap aws://ACCOUNT_ID/us-east-1

# 4. Validar y previsualizar
cdk synth
cdk diff --all
```

**Requisitos:** Python 3.11 · Node.js 22 (para el CDK CLI) · AWS CDK v2
(`npm install -g aws-cdk`) · AWS CLI configurado.

**Cuenta/región por defecto:** `050451404093` / `us-east-1` (sobreescribibles con
`-c account=...` / `-c region=...` o las env vars `CDK_DEFAULT_*`).

---

## Documentación relacionada

| Documento | Descripción |
|---|---|
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Procedimiento paso a paso de despliegue (incl. orden ECR → imágenes → stacks). |
| [`docs/DEPLOY_FLOW.md`](docs/DEPLOY_FLOW.md) | Diagrama del flujo completo de deploy. |
| [`docs/ON_OFF.md`](docs/ON_OFF.md) | Encender / apagar por CLI y costos aproximados. |
| `sward-docs/github-secrets-runbook.md` | Runbook para re-sincronizar GitHub Secrets tras reconstruir la infra. |
| `sward-docs/operaciones-encender-apagar.md` | Operación de encendido/apagado a nivel sistema. |

---

## Proyecto

**Universidad Peruana de Ciencias Aplicadas (UPC)** — Sistema SWARD,
plataforma de recomendación de aprendizaje adaptativo.
