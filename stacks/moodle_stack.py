from aws_cdk import (
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    custom_resources as cr,
)
from constructs import Construct

# Misma imagen y versión que el Moodle de pruebas (sward-moodle-test).
IMAGEN_MOODLE = "erseco/alpine-moodle:v4.5.11"

# Commit de sward-moodle-test del que se toma seed/setup_webservices.php. Fijo,
# para que un cambio en ese repositorio no altere una instancia ya desplegada.
SHA_SEED = "022c93025c1b49a282df3598b4e4556ca34c17b4"

# Guion de arranque de la instancia. Los @@VALORES@@ se reemplazan al sintetizar.
_ARRANQUE = r"""#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/sward-moodle.log) 2>&1
echo "== SWARD Moodle: arranque $(date -Is)"

install -d -m 700 /opt/moodle
cat > /opt/moodle/config.sh <<'EOF'
REGION=@@REGION@@
SITE_URL=@@SITE_URL@@
IP_PUBLICA=@@IP_PUBLICA@@
BUCKET=@@BUCKET@@
SECRETO_ADMIN=@@SECRETO_ADMIN@@
SECRETO_SMTP=@@SECRETO_SMTP@@
SECRETO_TOKEN=@@SECRETO_TOKEN@@
CORREO_ADMIN=@@CORREO_ADMIN@@
EOF
. /opt/moodle/config.sh

# 1. Esperar la IP elastica: la instancia no tiene otra IP publica, asi que sin
#    ella no hay salida a internet.
for i in $(seq 1 60); do
  T=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)
  IP=$(curl -s -H "X-aws-ec2-metadata-token: $T" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
  [ "$IP" = "$IP_PUBLICA" ] && break
  sleep 10
done

# 2. Swap de 2 GB: t3.small trae 2 GB de RAM para MariaDB y PHP juntos.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 3. Docker, compose, jq y cron.
dnf install -y docker jq cronie
systemctl enable --now docker crond
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 4. Contrasenas de la base: se generan una vez y no salen de la instancia.
if [ ! -f /opt/moodle/db.env ]; then
  ( umask 077; printf 'DB_PASS=%s\nDB_ROOT_PASS=%s\n' "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > /opt/moodle/db.env )
fi

# 5. secretos.sh arma los archivos de entorno desde Secrets Manager. Se vuelve a
#    correr (con actualizar.sh) cuando cambia el correo del proyecto.
cat > /opt/moodle/secretos.sh <<'EOF'
#!/bin/bash
set -euo pipefail
. /opt/moodle/config.sh
. /opt/moodle/db.env
leer() { aws secretsmanager get-secret-value --region "$REGION" --secret-id "$1" --query SecretString --output text; }
ADMIN=$(leer "$SECRETO_ADMIN")
SMTP=$(leer "$SECRETO_SMTP")
BACKEND=$(echo "$SMTP" | jq -r '.email_backend // ""')
SMTP_USER=$(echo "$SMTP" | jq -r '.smtp_user // ""')
SMTP_PASS=$(echo "$SMTP" | jq -r '.smtp_password // ""' | tr -d ' ')
if [ "$BACKEND" != "smtp" ] || [ -z "$SMTP_USER" ]; then
  echo "AVISO: $SECRETO_SMTP sin configurar; Moodle no podra enviar correos." >&2
  SMTP_USER=""
  SMTP_PASS=""
fi
umask 077
cat > /opt/moodle/mariadb.env <<ENV
MARIADB_DATABASE=moodle
MARIADB_USER=moodle
MARIADB_PASSWORD=$DB_PASS
MARIADB_ROOT_PASSWORD=$DB_ROOT_PASS
ENV
cat > /opt/moodle/moodle.env <<ENV
DB_TYPE=mariadb
DB_HOST=mariadb
DB_PORT=3306
DB_NAME=moodle
DB_USER=moodle
DB_PASS=$DB_PASS
MOODLE_USERNAME=admin
MOODLE_PASSWORD=$(echo "$ADMIN" | jq -r .contrasena)
MOODLE_EMAIL=$CORREO_ADMIN
MOODLE_SITENAME=SWARD
MOODLE_LANGUAGE=es
SITE_URL=$SITE_URL
REVERSEPROXY=true
SSLPROXY=true
AUTO_UPDATE_MOODLE=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_PROTOCOL=tls
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASS
MOODLE_MAIL_NOREPLY_ADDRESS=${SMTP_USER:-noreply@sward.local}
MOODLE_MAIL_PREFIX=[SWARD]
ENV
EOF

cat > /opt/moodle/actualizar.sh <<'EOF'
#!/bin/bash
# Relee los secretos y reinicia Moodle, que aplica el correo al arrancar.
set -euo pipefail
/opt/moodle/secretos.sh
cd /opt/moodle && docker compose up -d --force-recreate moodle
EOF

cat > /opt/moodle/respaldo.sh <<'EOF'
#!/bin/bash
# Respaldo de la base y de moodledata en S3. Corre cada noche por cron.
set -euo pipefail
. /opt/moodle/config.sh
. /opt/moodle/db.env
F=$(date -u +%Y-%m-%dT%H%M)
D=/opt/moodle/respaldos
mkdir -p "$D"
docker exec -e MYSQL_PWD="$DB_ROOT_PASS" sward-moodle-mariadb \
  mariadb-dump -uroot --single-transaction moodle | gzip > "$D/moodle-db-$F.sql.gz"
docker run --rm -v moodle_moodledata:/datos:ro -v "$D":/salida alpine \
  tar czf "/salida/moodledata-$F.tar.gz" -C /datos .
aws s3 cp "$D/moodle-db-$F.sql.gz" "s3://$BUCKET/$F/" --region "$REGION"
aws s3 cp "$D/moodledata-$F.tar.gz" "s3://$BUCKET/$F/" --region "$REGION"
rm -f "$D"/*-"$F".*
EOF
chmod 700 /opt/moodle/*.sh

cat > /opt/moodle/docker-compose.yml <<'EOF'
name: moodle
x-registro: &registro
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }
services:
  mariadb:
    <<: *registro
    image: docker.io/library/mariadb:11.4
    container_name: sward-moodle-mariadb
    env_file: mariadb.env
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]
    volumes: ["mariadb_data:/var/lib/mysql"]
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 15s
      timeout: 10s
      retries: 20
      start_period: 60s
    restart: unless-stopped
  moodle:
    <<: *registro
    image: docker.io/@@IMAGEN_MOODLE@@
    container_name: sward-moodle-app
    depends_on:
      mariadb: { condition: service_healthy }
    ports: ["80:8080"]
    env_file: moodle.env
    volumes: ["moodledata:/var/www/moodledata", "html:/var/www/html"]
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:8080/login/index.php || exit 1"]
      interval: 30s
      timeout: 15s
      retries: 30
      start_period: 300s
    restart: unless-stopped
volumes:
  mariadb_data: {}
  moodledata: {}
  html: {}
EOF

# 6. Arrancar y esperar la instalacion (la primera vez tarda varios minutos).
/opt/moodle/secretos.sh
cd /opt/moodle && docker compose up -d
for i in $(seq 1 90); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' sward-moodle-app)" = "healthy" ] && break
  sleep 20
done

# 6b. El sitio para los participantes: tema SWARD (solo «Mis cursos» en la barra)
#     y los ajustes de seed/validacion/configurar_sitio.php (entrada con correo,
#     hora de Lima, correos ocultos, sin correos por cada quiz...). Mismo código
#     que el Moodle local, en el commit fijado de sward-moodle-test.
mkdir -p /opt/moodle/repo
curl -fsSL "https://codeload.github.com/sward-UPC/sward-moodle-test/tar.gz/@@SHA_SEED@@" \
  | tar -xz --strip-components=1 -C /opt/moodle/repo
docker cp /opt/moodle/repo/moodle/theme/sward sward-moodle-app:/var/www/html/theme/sward
docker exec -u 0 sward-moodle-app sh -c 'chown -R "$(stat -c %u:%g /var/www/html/theme/boost)" /var/www/html/theme/sward'
docker exec sward-moodle-app php /var/www/html/admin/cli/upgrade.php --non-interactive
docker cp /opt/moodle/repo/seed/validacion/configurar_sitio.php sward-moodle-app:/tmp/configurar_sitio.php
docker exec sward-moodle-app php /tmp/configurar_sitio.php

# 7. Web services para SWARD: el token queda en Secrets Manager, de donde lo
#    lee ms-integracion-lms junto con la URL. token.sh se puede volver a correr.
cat > /opt/moodle/token.sh <<'EOF'
#!/bin/bash
set -euo pipefail
. /opt/moodle/config.sh
curl -fsSL -o /opt/moodle/setup_webservices.php \
  "https://raw.githubusercontent.com/sward-UPC/sward-moodle-test/@@SHA_SEED@@/seed/setup_webservices.php"
docker cp /opt/moodle/setup_webservices.php sward-moodle-app:/tmp/setup_webservices.php
SALIDA=$(docker exec sward-moodle-app php /tmp/setup_webservices.php)
echo "$SALIDA"
TOKEN=$(echo "$SALIDA" | grep '^MOODLE_TOKEN=' | cut -d= -f2)
[ -n "$TOKEN" ] || { echo "ERROR: no se obtuvo el token de web services" >&2; exit 1; }
aws secretsmanager put-secret-value --region "$REGION" --secret-id "$SECRETO_TOKEN" \
  --secret-string "$(jq -cn --arg u "$SITE_URL" --arg t "$TOKEN" '{moodle_base_url: $u, moodle_token: $t}')"
echo "Token guardado en $SECRETO_TOKEN"
EOF
chmod 700 /opt/moodle/token.sh
/opt/moodle/token.sh || echo "AVISO: token.sh fallo; volver a correrlo con Session Manager" >&2

# 8. Respaldo cada noche a las 03:00 UTC (22:00 en Lima).
echo '0 3 * * * root /opt/moodle/respaldo.sh >> /var/log/sward-moodle-respaldo.log 2>&1' > /etc/cron.d/sward-moodle-respaldo

echo "== SWARD Moodle listo: $SITE_URL ($(date -Is))"
"""


class MoodleStack(Stack):
    """Moodle en internet para los participantes externos del OE4.

    Los 30 estudiantes no están en ningún Moodle nuestro: resuelven en este los
    quizzes de la fase 1, y ms-integracion-lms sincroniza desde aquí. Por eso
    **no entra en el apagado nocturno** (stop.yml solo toca ECS, RDS y Lambdas):
    los estudiantes pueden entrar a cualquier hora.

    Flujo:
      estudiante ──HTTPS──► CloudFront (*.cloudfront.net) ──HTTP──► EC2 :80

    Una sola instancia EC2 con Docker corre la misma imagen de Moodle y MariaDB
    que el entorno de pruebas. Es lo más barato que funciona (unos 21 USD al mes:
    t3.small, 30 GB de disco y la IP pública); ECS con EFS y RDS costaría varias
    veces más para 31 usuarios.

    Seguridad:
      * El puerto 80 solo acepta a CloudFront (lista de prefijos administrada
        por AWS); no hay SSH: se entra con Session Manager.
      * La contraseña del administrador se genera en Secrets Manager
        (``sward/moodle-admin``) y las de la base, en la propia instancia.
      * El correo sale por la cuenta del proyecto, desde el mismo secreto que
        usa ms-usuarios (``sward/smtp``).
      * Al terminar de instalarse, la instancia genera el token de web services
        y lo guarda con la URL en ``sward/moodle-token``, de donde lo lee
        ms-integracion-lms.
      * Respaldo diario de la base y de moodledata en un bucket que se conserva
        aunque se destruya el stack.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        correo_admin: str,
        tipo_instancia: str = "t3.small",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Secretos ─────────────────────────────────────────────────────────
        admin = secretsmanager.Secret(
            self,
            "AdminMoodle",
            secret_name="sward/moodle-admin",
            description="Administrador del Moodle de SWARD (usuario admin)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"usuario": "admin"}',
                generate_string_key="contrasena",
                password_length=20,
                require_each_included_type=True,
                # Fuera los caracteres que rompen un archivo .env o la línea de
                # comandos del instalador de Moodle, que no los entrecomilla.
                exclude_characters=" \"'`$\\#*?[]{}()<>|&;!~^%",
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        smtp = secretsmanager.Secret.from_secret_name_v2(self, "Smtp", "sward/smtp")
        token = secretsmanager.Secret.from_secret_name_v2(
            self, "MoodleToken", "sward/moodle-token"
        )

        # ── Respaldos ────────────────────────────────────────────────────────
        respaldos = s3.Bucket(
            self,
            "Respaldos",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
            # Los datos de los participantes sobreviven a un cdk destroy.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── Red ──────────────────────────────────────────────────────────────
        grupo = ec2.SecurityGroup(
            self,
            "GrupoMoodle",
            vpc=vpc,
            description="Moodle de SWARD: HTTP solo desde CloudFront",
            allow_all_outbound=True,
        )
        # El id de la lista de prefijos de CloudFront cambia por región: se
        # consulta al desplegar en vez de fijarlo en el código.
        prefijos = cr.AwsCustomResource(
            self,
            "PrefijosCloudFront",
            on_create=cr.AwsSdkCall(
                service="EC2",
                action="describeManagedPrefixLists",
                parameters={
                    "Filters": [
                        {
                            "Name": "prefix-list-name",
                            "Values": ["com.amazonaws.global.cloudfront.origin-facing"],
                        }
                    ]
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    "cloudfront-origin-facing"
                ),
                output_paths=["PrefixLists.0.PrefixListId"],
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            install_latest_aws_sdk=False,
        )
        grupo.add_ingress_rule(
            ec2.Peer.prefix_list(
                prefijos.get_response_field("PrefixLists.0.PrefixListId")
            ),
            ec2.Port.tcp(80),
            "Solo CloudFront",
        )

        ip = ec2.CfnEIP(self, "IpMoodle", domain="vpc")
        # CloudFront necesita un nombre, no una IP: el DNS público que AWS
        # asigna a cada IP elástica se arma a partir de la propia IP.
        sufijo = (
            "compute-1.amazonaws.com"
            if self.region == "us-east-1"
            else f"{self.region}.compute.amazonaws.com"
        )
        dominio_origen = Fn.join(
            "",
            [
                "ec2-",
                Fn.join("-", Fn.split(".", ip.attr_public_ip)),
                ".",
                sufijo,
            ],
        )

        distribucion = cloudfront.Distribution(
            self,
            "DistribucionMoodle",
            comment="SWARD Moodle — HTTPS para los participantes",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    dominio_origen,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    http_port=80,
                    read_timeout=Duration.seconds(60),
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )
        url = f"https://{distribucion.distribution_domain_name}"

        # ── Instancia ────────────────────────────────────────────────────────
        rol = iam.Role(
            self,
            "RolMoodle",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                # Session Manager en lugar de SSH.
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                )
            ],
        )
        admin.grant_read(rol)
        smtp.grant_read(rol)
        token.grant_write(rol)
        respaldos.grant_put(rol)

        arranque = _ARRANQUE
        for clave, valor in {
            "REGION": self.region,
            "SITE_URL": url,
            "IP_PUBLICA": ip.attr_public_ip,
            "BUCKET": respaldos.bucket_name,
            "SECRETO_ADMIN": "sward/moodle-admin",
            "SECRETO_SMTP": "sward/smtp",
            "SECRETO_TOKEN": "sward/moodle-token",
            "CORREO_ADMIN": correo_admin,
            "IMAGEN_MOODLE": IMAGEN_MOODLE,
            "SHA_SEED": SHA_SEED,
        }.items():
            arranque = arranque.replace(f"@@{clave}@@", valor)

        instancia = ec2.Instance(
            self,
            "InstanciaMoodle",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType(tipo_instancia),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=grupo,
            role=rol,
            user_data=ec2.UserData.custom(arranque),
            # Sin IP pública automática: sale por la IP elástica, que es la que
            # conoce CloudFront. Así la IP no cambia si la instancia se reinicia.
            associate_public_ip_address=False,
            require_imdsv2=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        30,
                        encrypted=True,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                    ),
                )
            ],
        )
        ec2.CfnEIPAssociation(
            self,
            "IpMoodleAsociacion",
            allocation_id=ip.attr_allocation_id,
            instance_id=instancia.instance_id,
        )

        CfnOutput(self, "MoodleUrl", value=url, description="URL pública de Moodle")
        CfnOutput(
            self,
            "MoodleInstancia",
            value=instancia.instance_id,
            description="Para entrar con Session Manager o correr actualizar.sh",
        )
        CfnOutput(
            self,
            "MoodleRespaldos",
            value=respaldos.bucket_name,
            description="Bucket con los respaldos diarios (se conserva al destruir)",
        )
