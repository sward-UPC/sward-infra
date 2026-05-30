# sward-infra

Infraestructura como código (IaC) del sistema **SWARD** usando **AWS CDK en Python**.

## Stacks

| Stack | Recursos |
|---|---|
| `NetworkingStack` | VPC, subnets, security groups |
| `EcrStack` | 6× repositorio ECR `sward/<servicio>` + lifecycle policy |
| `SecretsStack` | `SECRET_KEY` (JWT), service keys, token Moodle (Secrets Manager) |
| `StorageStack` | S3 bucket de recursos educativos + modelos SAKT |
| `DatabaseStack` | 6× RDS PostgreSQL (credenciales en Secrets Manager) |
| `CacheStack` | ElastiCache Redis para ms-xai |
| `ServicesStack` | ECS Cluster + 6× Fargate Service + ALB (path routing) + Cloud Map |
| `LambdasStack` | EventBus + 4× Lambda + EventBridge rules + SQS con DLQ |

El despliegue se documenta en [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
(orden de stacks, bootstrap, build/push de imágenes a ECR antes de ECS).

## Requisitos

- Python 3.11
- AWS CDK v2: `npm install -g aws-cdk`
- AWS CLI configurado

## Comandos

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth
cdk deploy --all
```

## Documentación de estado

Ver [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) para el inventario actualizado del sistema.

## Proyecto

**TP202610051** — Universidad Peruana de Ciencias Aplicadas (UPC)  
Taller de Proyecto 1 / 2026
