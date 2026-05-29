# sward-infra

Infraestructura como código (IaC) del sistema **SWARD** usando **AWS CDK en Python**.

## Stacks

| Stack | Recursos |
|---|---|
| `NetworkingStack` | VPC, subnets, security groups |
| `DatabaseStack` | 6× RDS PostgreSQL + ElastiCache Redis |
| `ServicesStack` | EC2 / ECS + Amazon API Gateway |
| `LambdasStack` | 4× Lambda + EventBridge rules + SQS |
| `StorageStack` | S3 bucket de recursos educativos + modelos SAKT |

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
