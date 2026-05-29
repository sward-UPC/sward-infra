# CLAUDE.md — sward-infra

## Qué es este repo
Infraestructura como código (IaC) del sistema SWARD usando AWS CDK en Python.
Despliega todos los recursos AWS: VPC, RDS, ElastiCache, S3, API Gateway, Lambda triggers, EventBridge, SQS.

## Stack
- Python 3.11 / AWS CDK v2 / constructs

## Estructura de carpetas
```
stacks/
  networking_stack.py   # VPC, subnets
  database_stack.py     # 6× RDS PostgreSQL
  storage_stack.py      # S3 buckets (recursos + modelos)
  services_stack.py     # API Gateway skeleton
  lambdas_stack.py      # EventBridge, SQS, Lambda triggers
app.py                  # Entrada CDK
docs/
  SYSTEM_STATE.md       # ← Inventario global del sistema
```

## Comandos clave
- Instalar: `pip install -r requirements.txt`
- Synth: `cdk synth`
- Deploy: `cdk deploy --all`
- Deploy stack específico: `cdk deploy SwardDatabase`

## SYSTEM_STATE.md
El archivo `docs/SYSTEM_STATE.md` es el **inventario global** del sistema SWARD.
Actualizar al terminar cada sprint con el estado de cada repo y microservicio.

## Decisiones de diseño
- Una RDS instance por microservicio (database-per-service pattern).
- Bus de eventos único `sward-event-bus` en Amazon EventBridge.
- Bucket `sward-models` para checkpoints del modelo SAKT (cargados en startup por ms-recomendacion).
