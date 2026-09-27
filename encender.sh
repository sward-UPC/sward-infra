#!/bin/sh
# Enciende SWARD sin desplegar nada: arranca lo que `apagar.sh` detuvo.
#
#     ./encender.sh
#
# Sirve mientras los stacks sigan en pie. Si se destruyeron, esto no vale y hay
# que seguir el despliegue completo de docs/ENCENDER_Y_APAGAR.md.
#
# El orden importa. La NAT va primera porque las tareas de Fargate viven en las
# subredes privadas y sin ella no alcanzan ECR ni Secrets Manager: arrancarian
# para morirse. La base va antes que los servicios por lo mismo. Y `redis` antes
# que los seis, que lo leen al calentar sus caches.
set -e
CL=sward-cluster

id_por_nombre() {
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=*$1*" \
    --query "Reservations[].Instances[?State.Name!='terminated'].InstanceId | [0][0]" \
    --output text
}

esperar_ec2() {
  i=0
  while [ $i -lt 30 ]; do
    e=$(aws ec2 describe-instances --instance-ids "$1" \
        --query "Reservations[].Instances[].State.Name" --output text)
    [ "$e" = "running" ] && return 0
    echo "    $2: $e"
    i=$((i + 1)); sleep 10
  done
  return 1
}

NAT=$(id_por_nombre NatInstance)
MOODLE=$(id_por_nombre InstanciaMoodle)
BASE=$(aws rds describe-db-instances --query "DBInstances[0].DBInstanceIdentifier" --output text)

echo "1/4  la NAT, que es de quien depende todo lo que vive en las subredes privadas"
aws ec2 start-instances --instance-ids "$NAT" --query "StartingInstances[].CurrentState.Name" --output text
esperar_ec2 "$NAT" NAT

echo "2/4  la base y Moodle, en paralelo"
aws rds start-db-instance --db-instance-identifier "$BASE" \
  --query "DBInstance.DBInstanceStatus" --output text || echo "    (ya estaba arrancando)"
aws ec2 start-instances --instance-ids "$MOODLE" \
  --query "StartingInstances[].CurrentState.Name" --output text

echo "3/4  esperando a que la base este disponible (entre cinco y diez minutos)"
i=0
while [ $i -lt 60 ]; do
  e=$(aws rds describe-db-instances --db-instance-identifier "$BASE" \
      --query "DBInstances[0].DBInstanceStatus" --output text)
  [ "$e" = "available" ] && break
  echo "    base: $e"
  i=$((i + 1)); sleep 20
done
if [ "$e" != "available" ]; then
  echo "LA BASE NO LLEGO A available. No subo los servicios: se quedarian"
  echo "reintentando contra una base apagada y gastando igual."
  exit 1
fi

echo "4/4  los servicios"
aws ecs update-service --cluster "$CL" --service redis --desired-count 1 \
  --query "service.desiredCount" --output text >/dev/null
sleep 30
for s in $(aws ecs list-services --cluster "$CL" --query "serviceArns[]" --output text \
           | tr '\t' '\n' | sed 's|.*/||' | grep -v '^redis$'); do
  aws ecs update-service --cluster "$CL" --service "$s" --desired-count 1 \
    --query "service.desiredCount" --output text >/dev/null
  echo "    $s"
done

echo "esperando a que corran"
i=0
while [ $i -lt 30 ]; do
  faltan=$(aws ecs describe-services --cluster "$CL" \
    --services $(aws ecs list-services --cluster "$CL" --query "serviceArns[]" --output text \
                 | tr '\t' '\n' | sed 's|.*/||') \
    --query "length(services[?runningCount<\`1\`])" --output text)
  [ "$faltan" = "0" ] && break
  echo "    sin arrancar todavia: $faltan"
  i=$((i + 1)); sleep 20
done

echo
echo "--- estado ---"
aws ecs describe-services --cluster "$CL" \
  --services $(aws ecs list-services --cluster "$CL" --query "serviceArns[]" --output text \
               | tr '\t' '\n' | sed 's|.*/||') \
  --query "services[].{n:serviceName,d:desiredCount,r:runningCount}" --output text
aws ec2 describe-instances --instance-ids "$NAT" "$MOODLE" \
  --query "Reservations[].Instances[].{e:State.Name,ip:PublicIpAddress}" --output text
aws rds describe-db-instances --db-instance-identifier "$BASE" \
  --query "DBInstances[0].DBInstanceStatus" --output text
echo
echo "Comprueba que responde de verdad, no solo que los contenedores estan arriba:"
echo "  curl -s -X POST https://dt2mpuhca1dmv.cloudfront.net/api/v1/auth/login \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"correo\":\"nadie@upc.edu.pe\",\"password\":\"ClaveFalsa123\"}'"
echo "Un 401 con «Credenciales invalidas» significa que la cadena entera funciona:"
echo "para saber que ese correo no existe tuvo que consultar la base."
