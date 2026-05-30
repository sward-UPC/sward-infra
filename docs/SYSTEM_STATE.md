# SYSTEM STATE — SWARD

Inventario actualizado del sistema. Actualizar al final de cada sprint.

**Última actualización:** 2026-05-30  
**Sprint actual:** 0 — Fundaciones

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

Ver [`DEPLOYMENT.md`](DEPLOYMENT.md) para el procedimiento de despliegue.

---

## Estado de los Repositorios

| Repo | Sprint | Estado | URL |
|---|---|---|---|
| sward-shared | 0 | ✅ Implementado | https://github.com/sward-UPC/sward-shared |
| sward-infra | 0 | ✅ Skeleton | https://github.com/sward-UPC/sward-infra |
| sward-ms-usuarios | 1 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-usuarios |
| sward-ms-integracion-lms | 2 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-integracion-lms |
| sward-ms-trazabilidad | 3 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-trazabilidad |
| sward-ms-cursos-recursos | 4 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-cursos-recursos |
| sward-ms-recomendacion | 4 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-recomendacion |
| sward-ms-xai | 5 | ⏳ Pendiente | https://github.com/sward-UPC/sward-ms-xai |
| sward-lambda-moodle-sync | 2 | ⏳ Pendiente | https://github.com/sward-UPC/sward-lambda-moodle-sync |
| sward-lambda-interacciones | 3 | ⏳ Pendiente | https://github.com/sward-UPC/sward-lambda-interacciones |
| sward-lambda-alertas | 5 | ⏳ Pendiente | https://github.com/sward-UPC/sward-lambda-alertas |
| sward-lambda-recursos | 4 | ⏳ Pendiente | https://github.com/sward-UPC/sward-lambda-recursos |

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
