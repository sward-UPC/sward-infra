# SYSTEM STATE — SWARD

Inventario actualizado del sistema. Actualizar al final de cada sprint.

**Última actualización:** 2026-06-02  
**Sprint actual:** Completado — Backend production-ready

---

## Infraestructura (sward-infra · AWS CDK Python)

8 stacks. Orden de dependencia:
`networking → ecr · secrets · storage → database · cache → services → lambdas`.

| Stack | ID CDK | Recursos |
|---|---|---|
| `NetworkingStack` | `SwardNetworking` | VPC (2 AZ), subnets pública/privada/aislada, NAT |
| `EcrStack` | `SwardEcr` | 6× repo ECR `sward/<servicio>` + lifecycle (10 imgs) |
| `SecretsStack` | `SwardSecrets` | JWT `SECRET_KEY`, 6× `SERVICE_KEY`, token Moodle |
| `StorageStack` | `SwardStorage` | S3 recursos educativos + S3 modelos SAKT |
| `DatabaseStack` | `SwardDatabase` | 6× RDS PostgreSQL 15 (t3.micro), credenciales en Secrets Manager |
| `CacheStack` | `SwardCache` | ElastiCache Redis (cache.t3.micro) para ms-xai |
| `ServicesStack` | `SwardServices` | ECS Cluster + 6× Fargate Service/TaskDef + ALB (path routing) + Cloud Map |
| `LambdasStack` | `SwardLambdas` | EventBus + 4× Lambda + reglas EventBridge + SQS con DLQ |

**Routing externo (ALB, HTTP:80 — TODO ACM/HTTPS):**

| Path(s) | Servicio | Prioridad |
|---|---|---|
| `/auth*` `/users*` `/admin*` | usuarios | 10 |
| `/lms*` | integracion-lms | 20 |
| `/interactions*` `/students*` `/dashboard*` | trazabilidad | 30 |
| `/courses*` `/resources*` | cursos-recursos | 40 |
| `/recommendations*` | recomendacion | 50 |
| `/xai*` | xai | 60 |

Health check ALB: `GET /health` (HTTP 200). Comunicación service-to-service
interna vía Cloud Map (DNS privado `<servicio>.sward.local:8000`).

Inyección de config en ECS: `ENVIRONMENT=production`, `DATABASE_HOST/PORT/NAME`,
`EVENTBRIDGE_BUS_NAME`, `*_SERVICE_URL` (env en claro); `DB_USERNAME`,
`DB_PASSWORD`, `SECRET_KEY`, `SERVICE_KEY`, `MOODLE_TOKEN`, `REDIS_URL` (xai)
desde Secrets Manager. La app compone `DATABASE_URL` con los componentes.

Ver [`DEPLOYMENT.md`](DEPLOYMENT.md) y [`DEPLOY_FLOW.md`](DEPLOY_FLOW.md) para el procedimiento y diagrama completo de despliegue.

---

## Estado de los Repositorios

| Repo | Estado | Tests | OpenAPI | CI/CD | GHCR |
|---|---|---|---|---|---|
| sward-shared | ✅ Implementado | ✅ | — | ✅ | — |
| sward-infra | ✅ 8 stacks CDK | — | — | ✅ diff+deploy | — |
| sward-ms-usuarios | ✅ Completo | ✅ 19/19 | ✅ Enriquecida | ✅ | ✅ |
| sward-ms-integracion-lms | ✅ Completo | ✅ 11/11 | ✅ Enriquecida | ✅ | ✅ |
| sward-ms-trazabilidad | ✅ Completo | ✅ 15/15 | ✅ Enriquecida | ✅ | ✅ |
| sward-ms-cursos-recursos | ✅ Completo | ✅ 15/15 | ✅ Enriquecida | ✅ | ✅ |
| sward-ms-recomendacion | ✅ Completo | ✅ 14/14 | ✅ Enriquecida | ✅ | ✅ |
| sward-ms-xai | ✅ Completo | ✅ 7/7 | ✅ Enriquecida | ✅ | ✅ |
| sward-lambda-moodle-sync | ✅ Completo | ✅ 4/4 | — | ✅ | ✅ |
| sward-lambda-interacciones | ✅ Completo | ✅ 9/9 | — | ✅ | ✅ |
| sward-lambda-alertas | ✅ Completo | ✅ 12/12 | — | ✅ | ✅ |
| sward-lambda-recursos | ✅ Completo | ✅ 18/18 | — | ✅ | ✅ |
| sward-moodle-test | ✅ Entorno pruebas | — | — | — | — |

---

## Puertos de los microservicios (local)

| Servicio | Puerto local |
|---|---|
| sward-ms-usuarios | 8001 |
| sward-ms-integracion-lms | 8002 |
| sward-ms-trazabilidad | 8003 |
| sward-ms-cursos-recursos | 8004 |
| sward-ms-recomendacion | 8005 |
| sward-ms-xai | 8006 |

---

## Variables de entorno requeridas (nombres, sin valores)

### Compartidas (todos los microservicios)
```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
EVENTBRIDGE_BUS_NAME=sward-event-bus
ENVIRONMENT=development
```

### sward-ms-usuarios
```
SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60
```

### sward-ms-recomendacion
```
SAKT_MODEL_S3_KEY=sakt/v1.0/model.pth
AWS_S3_MODEL_BUCKET=sward-models
TRAZABILIDAD_SERVICE_URL=http://localhost:8003
CURSOS_SERVICE_URL=http://localhost:8004
XAI_SERVICE_URL=http://localhost:8006
```

### sward-ms-xai
```
REDIS_URL=redis://localhost:6379/0
```

### sward-ms-integracion-lms
```
MOODLE_BASE_URL=https://moodle.example.com
MOODLE_TOKEN=
MOODLE_MOCK=true
```

---

## CI/CD

### Workflows centralizados (`sward-UPC/.github`)

| Workflow | Trigger | Acción |
|---|---|---|
| `ci-microservice.yml` | push/PR a `main` | lint + bandit + tests |
| `ci-lambda.yml` | push/PR a `main` | lint + tests |
| `build-push-ghcr.yml` | push a `deploy` | build Docker + push GHCR + deploy AWS (si `SEND_TO_AWS=true`) |

### GitHub Secrets (org level — `sward-UPC`)

| Secret | Descripción |
|---|---|
| `AWS_ACCESS_KEY_ID` | Credencial IAM para deploy |
| `AWS_SECRET_ACCESS_KEY` | Credencial IAM para deploy |
| `AWS_REGION` | Región AWS (`us-east-1`) |
| `SEND_TO_AWS` | `false` (cambiar a `true` para activar deploy automático a ECS/Lambda) |

### Imágenes Docker (GHCR)

```
ghcr.io/sward-upc/sward-ms-<nombre>:<timestamp>
ghcr.io/sward-upc/sward-lambda-<nombre>:<timestamp>
```

Tag formato: `YYYY-MM-DD-HHmmss` (UTC)

---

## Eventos de dominio publicados

| Evento | Publicado por | Consumido por |
|---|---|---|
| `sward.usuarios.UsuarioAutenticado` | ms-usuarios | — |
| `sward.lms.DatosLmsSincronizados` | ms-integracion-lms | ms-trazabilidad, ms-cursos-recursos |
| `sward.trazabilidad.InteraccionRegistrada` | ms-trazabilidad | lambda-interacciones (SQS) |
| `sward.recomendacion.RecomendacionGenerada` | ms-recomendacion | lambda-alertas (EventBridge) |
| `sward.xai.ExplicacionGenerada` | ms-xai | — |
| `sward.cursos.RecursoActualizado` | ms-cursos-recursos | lambda-recursos (S3) |

---

## Bases de datos

| BD | Microservicio | Tablas principales |
|---|---|---|
| usuarios_db | ms-usuarios | users, roles, permissions, user_roles, sessions, audit_logs |
| integracion_lms_db | ms-integracion-lms | lms_courses, lms_activities, lms_grades, lms_interactions |
| trazabilidad_db | ms-trazabilidad | interactions, activity_responses, academic_progress, indicators |
| cursos_recursos_db | ms-cursos-recursos | courses, activities, resources, resource_metadata |
| recomendacion_db | ms-recomendacion | recommendations, recommendation_items, kt_predictions |
| xai_db | ms-xai | explanations, attention_weights, explanatory_evidence, xai_visualizations |
