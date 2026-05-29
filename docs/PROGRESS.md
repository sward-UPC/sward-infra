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
- [ ] Redis ElastiCache (para ms-xai) — agregar en Sprint 5
- [ ] ECS Fargate tasks para los microservicios
- [ ] GitHub Actions CI para cdk synth
- [ ] `cdk deploy` real en AWS staging
