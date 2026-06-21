# SWARD — Encender y Apagar

> Solo enciende cuando estés desarrollando o grabando demo.
> Apaga siempre al terminar — RDS y ECS son los componentes más caros.

## Prerequisitos (una sola vez)

```bash
cd sward-infra
source .venv/bin/activate
export AWS_PROFILE=sward
```

---

## ENCENDER

### Opción A — Solo ECS (microservicios, sin base de datos fría)
Si RDS ya estaba corriendo (primer arranque del día):

```bash
# Escalar todos los servicios ECS a 1 tarea
aws ecs update-service --cluster SwardCluster --service sward-usuarios       --desired-count 1
aws ecs update-service --cluster SwardCluster --service sward-trazabilidad   --desired-count 1
aws ecs update-service --cluster SwardCluster --service sward-recomendacion  --desired-count 1
aws ecs update-service --cluster SwardCluster --service sward-cursos-recursos --desired-count 1
aws ecs update-service --cluster SwardCluster --service sward-integracion-lms --desired-count 1
aws ecs update-service --cluster SwardCluster --service sward-xai            --desired-count 1
```

### Opción B — Levantar todo desde cero (primera vez o tras destruir)

```bash
cdk deploy --all --require-approval never
```

### Verificar que todo está arriba

```bash
aws ecs list-services --cluster SwardCluster
aws ecs describe-services --cluster SwardCluster \
  --services sward-usuarios sward-trazabilidad sward-recomendacion \
  --query 'services[*].{name:serviceName,running:runningCount,desired:desiredCount}'
```

---

## APAGAR

### Opción A — Solo pausar ECS (RDS sigue corriendo, ~$0.50/h)
Para una pausa corta (menos de un día):

```bash
for svc in sward-usuarios sward-trazabilidad sward-recomendacion sward-cursos-recursos sward-integracion-lms sward-xai; do
  aws ecs update-service --cluster SwardCluster --service $svc --desired-count 0
done
echo "ECS apagado. RDS sigue corriendo."
```

### Opción B — Destruir todo (pausa larga / fin de sprint)
**Advertencia: borra la base de datos. Asegúrate de tener backup si necesitas los datos.**

```bash
cdk destroy --all --force
```

Para destruir solo partes (ej. conservar RDS):

```bash
cdk destroy SwardServices SwardLambdas SwardCloudfront --force
```

---

## Costos aproximados mientras está ENCENDIDO

| Componente | Costo/hora |
|---|---|
| RDS PostgreSQL (db.t3.micro × 6) | ~$0.85 |
| ECS Fargate (6 servicios, 0.25 vCPU/512 MB c/u) | ~$0.15 |
| ElastiCache Redis (cache.t3.micro) | ~$0.017 |
| ALB | ~$0.008 |
| CloudFront | ~$0 (free tier) |
| **Total encendido** | **~$1.03/hora** |

Con ECS apagado (Opción A): ~$0.88/hora (RDS sigue sumando).
Con todo destruido (Opción B): $0/hora.

---

## URL del sistema

Después del deploy, busca el output de CloudFront:

```bash
aws cloudformation describe-stacks --stack-name SwardCloudfront \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text
```
