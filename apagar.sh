#!/bin/sh
# Apaga SWARD sin destruir nada: deja los stacks en pie y los datos intactos.
#
#     ./apagar.sh
#
# Esto es lo que va entre la fase 1 y la fase 2, y cada noche mientras se este
# usando. NO es el apagado de despues de un ensayo: para borrarlo todo esta el
# `cdk destroy` de docs/ENCENDER_Y_APAGAR.md.
#
# Lo que deja de cobrarse: las siete tareas de Fargate, la base y las dos
# instancias EC2.
#
# Lo que sigue cobrandose, y por eso el suelo son unos 1,2 a 1,4 USD al dia: el
# balanceador, los discos, las IP fijas y los once secretos. Se cobran encendido
# o apagado, asi que apagar de noche ahorra menos de lo que parece. El unico modo
# de bajar de ese suelo es destruir los stacks, y eso se lleva los datos y cuesta
# una hora de volver a levantar.
#
# El orden es el inverso del encendido: primero los servicios, que son quienes
# hablan con la base, y la NAT al final, que es de quien dependen los demas para
# salir a internet.
set -e
CL=sward-cluster

id_por_nombre() {
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=*$1*" \
    --query "Reservations[].Instances[?State.Name!='terminated'].InstanceId | [0][0]" \
    --output text
}

NAT=$(id_por_nombre NatInstance)
MOODLE=$(id_por_nombre InstanciaMoodle)
BASE=$(aws rds describe-db-instances --query "DBInstances[0].DBInstanceIdentifier" --output text)
SERVICIOS=$(aws ecs list-services --cluster "$CL" --query "serviceArns[]" --output text \
            | tr '\t' '\n' | sed 's|.*/||')

echo "1/4  los servicios a cero"
for s in $SERVICIOS; do
  aws ecs update-service --cluster "$CL" --service "$s" --desired-count 0 \
    --query "service.desiredCount" --output text >/dev/null
  echo "    $s"
done

echo "2/4  esperando a que suelten las tareas (hasta cinco minutos)"
i=0
while [ $i -lt 15 ]; do
  vivas=$(aws ecs describe-services --cluster "$CL" --services $SERVICIOS \
    --query "sum(services[].runningCount)" --output text)
  [ "$vivas" = "0" ] || [ "$vivas" = "0.0" ] && break
  echo "    todavia corriendo: $vivas"
  i=$((i + 1)); sleep 20
done

echo "3/4  la base y Moodle"
aws rds stop-db-instance --db-instance-identifier "$BASE" \
  --query "DBInstance.DBInstanceStatus" --output text
aws ec2 stop-instances --instance-ids "$MOODLE" \
  --query "StoppingInstances[].CurrentState.Name" --output text

echo "4/4  la NAT, al final"
aws ec2 stop-instances --instance-ids "$NAT" \
  --query "StoppingInstances[].CurrentState.Name" --output text

echo
echo "--- comprobacion ---"
echo "instancias encendidas (deberia quedar vacio en un minuto o dos):"
aws ec2 describe-instances --filters Name=instance-state-name,Values=running,pending \
  --query "Reservations[].Instances[].InstanceId" --output text
echo "base:"
aws rds describe-db-instances --db-instance-identifier "$BASE" \
  --query "DBInstances[0].DBInstanceStatus" --output text
echo "tareas de Fargate deseadas:"
aws ecs describe-services --cluster "$CL" --services $SERVICIOS \
  --query "sum(services[].desiredCount)" --output text
echo
echo "La base se reinicia sola a los siete dias: si el apagado va a durar mas,"
echo "hay que volver a detenerla o destruir los stacks."
