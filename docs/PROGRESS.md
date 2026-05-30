# PROGRESS — sward-infra

## Sprint 0 — 2026-05-29

### Implementado
- [x] Estructura CDK Python con 5 stacks
- [x] NetworkingStack — VPC con subnets públicas, privadas e isolated
- [x] DatabaseStack — 6× RDS PostgreSQL (una por microservicio)
- [x] StorageStack — S3 buckets para recursos educativos y modelos SAKT
- [x] ServicesStack — API Gateway REST skeleton
- [x] LambdasStack — EventBridge bus + SQS queue skeleton
- [x] SYSTEM_STATE.md — inventario global del sistema
- [x] CLAUDE.md

### Pendiente
- [x] GitHub Actions CI para cdk synth

## Sprint 0 (cont.) — 2026-05-30 · Infra de despliegue

### Implementado
- [x] EcrStack — 6× repositorio ECR `sward/<servicio>` con lifecycle policy
- [x] SecretsStack — SECRET_KEY (JWT), service keys, token Moodle en Secrets Manager
- [x] CacheStack — ElastiCache Redis (cache.t3.micro) para ms-xai
- [x] ServicesStack reescrito — ECS Cluster + 6× Fargate Service/TaskDef (256/512),
      ALB con path-based routing, Cloud Map para s2s, health check `/health`
- [x] DatabaseStack — credenciales RDS generadas en Secrets Manager + SG compartido
- [x] LambdasStack — 4× Lambda, reglas EventBridge (InteraccionRegistrada,
      RecomendacionGenerada, schedule 15min, S3 ObjectCreated), SQS con DLQ
- [x] app.py — wiring de los 8 stacks con dependencias correctas
- [x] docs/DEPLOYMENT.md — orden de deploy, bootstrap, build/push de imágenes
- [x] CI — ruff format --check + cdk synth (cdk.context.json para AZ cacheadas)
- [x] .gitignore — excluir cdk.out/ y .cdk.staging/

### Pendiente
- [ ] Listener HTTPS + certificado ACM (TODO en services_stack.py)
- [ ] Auto-scaling de los Fargate Services
- [ ] `cdk deploy` real en AWS staging
