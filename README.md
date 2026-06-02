# sward-infra

Infraestructura como código (IaC) del sistema **SWARD** — plataforma de aprendizaje adaptativo para estudiantes universitarios de Lima Metropolitana.

Implementado con **AWS CDK en Python 3.11**.

[![CI](https://github.com/sward-UPC/sward-infra/actions/workflows/ci.yml/badge.svg)](https://github.com/sward-UPC/sward-infra/actions/workflows/ci.yml)

---

## Arquitectura

```
sward-infra (CDK)
├── SwardNetworking   → VPC · 2 AZ · Subnets pública/privada/aislada · NAT
├── SwardEcr          → 6× ECR repos (imágenes Docker microservicios)
├── SwardSecrets      → JWT SECRET_KEY · 6× SERVICE_KEY · MOODLE_TOKEN
├── SwardStorage      → S3 recursos educativos · S3 modelos SAKT
├── SwardDatabase     → 6× RDS PostgreSQL 15 (t3.micro)
├── SwardCache        → ElastiCache Redis (cache.t3.micro)
├── SwardServices     → ECS Fargate · 6× Service · ALB path routing · Cloud Map
└── SwardLambdas      → 4× Lambda · EventBridge · SQS · DLQ
```

### Routing ALB

| Path | Microservicio |
|---|---|
| `/auth*` `/users*` `/admin*` | sward-ms-usuarios |
| `/lms*` | sward-ms-integracion-lms |
| `/interactions*` `/students*` `/dashboard*` | sward-ms-trazabilidad |
| `/courses*` `/resources*` | sward-ms-cursos-recursos |
| `/recommendations*` | sward-ms-recomendacion |
| `/xai*` | sward-ms-xai |

### Lambdas

| Función | Trigger | Acción |
|---|---|---|
| `sward-lambda-moodle-sync` | EventBridge (15 min) | Sincroniza datos desde Moodle |
| `sward-lambda-interacciones` | SQS | Normaliza `InteraccionRegistradaEvent` |
| `sward-lambda-alertas` | EventBridge rule | Evalúa riesgo académico |
| `sward-lambda-recursos` | S3 ObjectCreated | Actualiza `MetadataRecurso` |

---

## Flujo de Deploy

Ver diagrama completo en [`docs/DEPLOY_FLOW.md`](docs/DEPLOY_FLOW.md).

```
Cambio de código   →  git push deploy (en cada repo)  →  GHCR + ECS/Lambda
Cambio de infra    →  git push deploy (sward-infra)   →  cdk diff → aprobación → cdk deploy
```

### CI (rama `main`)

1. `ruff` lint + format
2. `cdk synth` — valida los stacks
3. `cdk diff` — muestra qué cambiaría en AWS

### CD (rama `deploy`)

1. `cdk synth` + `cdk diff`
2. ⏸ **Aprobación manual** (GitHub Environment `production`)
3. `cdk deploy --all`

---

## Requisitos

- Python 3.11
- Node.js 22 (para CDK CLI)
- AWS CDK v2: `npm install -g aws-cdk`
- AWS CLI configurado (`aws configure`)

---

## Setup local

```bash
# 1. Clonar y crear entorno virtual
git clone https://github.com/sward-UPC/sward-infra.git
cd sward-infra
python -m venv .venv && source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt -r requirements-dev.txt

# 3. Bootstrap CDK (solo la primera vez por cuenta/región)
cdk bootstrap aws://ACCOUNT_ID/us-east-1

# 4. Verificar stacks
cdk synth

# 5. Ver qué cambiaría en AWS
cdk diff --all

# 6. Deployar
cdk deploy --all
```

---

## Stacks

| Stack | ID CDK | Descripción |
|---|---|---|
| `NetworkingStack` | `SwardNetworking` | VPC (2 AZ), subnets, NAT Gateway, security groups |
| `EcrStack` | `SwardEcr` | 6 repos ECR + lifecycle policy (10 imágenes max) |
| `SecretsStack` | `SwardSecrets` | JWT secret, service keys, Moodle token en Secrets Manager |
| `StorageStack` | `SwardStorage` | S3 recursos educativos + modelos SAKT |
| `DatabaseStack` | `SwardDatabase` | 6× RDS PostgreSQL 15 (t3.micro), credenciales en Secrets Manager |
| `CacheStack` | `SwardCache` | ElastiCache Redis (cache.t3.micro) para ms-xai |
| `ServicesStack` | `SwardServices` | ECS Cluster + 6× Fargate service + ALB + Cloud Map DNS interno |
| `LambdasStack` | `SwardLambdas` | EventBus + 4× Lambda + EventBridge rules + SQS + DLQ |

### Orden de dependencias

```
SwardNetworking
    ├── SwardDatabase
    ├── SwardCache
    └── SwardServices ← SwardEcr · SwardSecrets · SwardDatabase · SwardCache
            └── SwardLambdas ← SwardStorage (S3 notifica a lambda-recursos)
```

---

## Variables de entorno requeridas

### GitHub Secrets (org `sward-UPC`)

| Secret | Descripción |
|---|---|
| `AWS_ACCESS_KEY_ID` | Credencial IAM |
| `AWS_SECRET_ACCESS_KEY` | Credencial IAM |
| `AWS_REGION` | Región (`us-east-1`) |
| `SEND_TO_AWS` | `false` → `true` activa deploy automático a ECS/Lambda |

### Local (`.env`)

```bash
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

---

## Documentación

| Documento | Descripción |
|---|---|
| [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) | Estado actual de todos los repos y recursos |
| [`docs/DEPLOY_FLOW.md`](docs/DEPLOY_FLOW.md) | Diagrama Mermaid del flujo completo de deploy |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Procedimiento paso a paso de despliegue |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | Log de avances por sprint |

---

## Proyecto

**TP202610051** — Universidad Peruana de Ciencias Aplicadas (UPC)  
Taller de Proyecto 1 — 2026  
Sistema SWARD — Adaptive Learning Recommendation Platform
