from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
    aws_servicediscovery as servicediscovery,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

# Definición declarativa de los 6 microservicios y su routing en el ALB.
#   key             -> nombre lógico (coincide con ECR repo "sward/<key>" y
#                      con la clave en DatabaseStack.instances)
#   paths           -> patrones de path en el ALB que enrutan a este servicio
#   priority        -> prioridad de la regla del listener (única)
SERVICES = {
    "usuarios": {
        "paths": ["/auth*", "/users*", "/admin*"],
        "priority": 10,
    },
    "integracion-lms": {
        "paths": ["/lms*"],
        "priority": 20,
    },
    "trazabilidad": {
        "paths": ["/interactions*", "/students*", "/dashboard*"],
        "priority": 30,
    },
    "cursos-recursos": {
        "paths": ["/courses*", "/resources*"],
        "priority": 40,
    },
    "recomendacion": {
        "paths": ["/recommendations*"],
        "priority": 50,
    },
    "xai": {
        "paths": ["/xai*"],
        "priority": 60,
    },
}

CONTAINER_PORT = 8000

# Grafo de callers s2s: quién está autorizado a llamar a cada servicio.
# CDK inyecta la SERVICE_KEY de cada caller como ECS Secret en el receptor,
# que la recibe como env var AUTHORIZED_<CALLER>_KEY y la valida en el header
# X-Service-Key. Si el set está vacío el middleware pasa todo (modo desarrollo).
AUTHORIZED_CALLERS: dict[str, list[str]] = {
    "integracion-lms": ["trazabilidad", "usuarios"],  # usuarios: lookup en registro
    "trazabilidad": [
        "recomendacion",
        "integracion-lms",
        "usuarios",
    ],  # usuarios: KPI dominio plataforma
    "cursos-recursos": [
        "recomendacion",
        "integracion-lms",
    ],  # integracion-lms: sync del catálogo de cursos
    "xai": ["recomendacion"],
    "recomendacion": [],  # solo JWT de usuarios finales
    "usuarios": ["trazabilidad"],  # /internal/users/by-ids para enriquecer dashboard
}


class ServicesStack(Stack):
    """ECS Fargate + Application Load Balancer para los 6 microservicios SWARD.

    Topología:
      * Un ECS Cluster en la VPC con un namespace de Cloud Map (``sward.local``)
        para *service discovery* interno (comunicación service-to-service por
        DNS privado, p. ej. ``trazabilidad.sward.local:8000``).
      * Una TaskDefinition + FargateService por microservicio (256 CPU / 512 MB).
        Cada task toma su imagen del repositorio ECR ``sward/<servicio>``.
      * Un ALB público con un listener y reglas de *path-based routing*.

    Decisión de routing s2s: el tráfico **externo** (clientes) entra por el ALB
    con path-based routing; la comunicación **interna** entre microservicios usa
    Cloud Map (DNS privado), que es lo más simple y evita exponer servicios
    internos o pagar saltos extra por el ALB.

    Inyección de configuración (sin hardcodear secretos):
      * ENVIRONMENT, DATABASE_HOST/PORT/NAME, EVENTBRIDGE_BUS_NAME, *_SERVICE_URL
        van como variables de entorno en texto plano.
      * DB_USERNAME, DB_PASSWORD, SECRET_KEY, SERVICE_KEY, MOODLE_TOKEN se
        inyectan como ``secrets`` desde Secrets Manager (cifrados en tránsito).
        La app compone ``DATABASE_URL`` a partir de los componentes.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        db_instances: dict,
        db_credentials: dict | None = None,
        db_security_group: ec2.ISecurityGroup | None = None,
        jwt_secret: secretsmanager.ISecret | None = None,
        service_keys: dict | None = None,
        moodle_token: secretsmanager.ISecret | None = None,
        admin_seed_secret: secretsmanager.ISecret | None = None,
        event_bus_name: str = "sward-event-bus",
        models_bucket: s3.IBucket | None = None,
        is_dev: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        service_keys = service_keys or {}

        # --- Cluster + namespace de Cloud Map para service discovery interno ---
        # NOTA: NO usamos enable_fargate_capacity_providers=True porque genera un
        # custom resource de CDK que bloquea la eliminación del cluster en rollbacks.
        # FARGATE y FARGATE_SPOT están disponibles en todos los clusters por defecto
        # en AWS, así que capacity_provider_strategies en cada servicio funciona igual.
        self.cluster = ecs.Cluster(
            self,
            "SwardCluster",
            vpc=vpc,
            cluster_name="sward-cluster",
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )
        self.namespace = self.cluster.add_default_cloud_map_namespace(
            name="sward.local",
        )

        # --- Security group compartido por todas las tasks de ECS ---
        self.service_security_group = ec2.SecurityGroup(
            self,
            "EcsServiceSecurityGroup",
            vpc=vpc,
            description="SG de las tasks Fargate de SWARD",
            allow_all_outbound=True,
        )
        # Permitir tráfico entre microservicios (s2s vía Cloud Map).
        self.service_security_group.add_ingress_rule(
            peer=self.service_security_group,
            connection=ec2.Port.tcp(CONTAINER_PORT),
            description="Trafico service-to-service entre tasks SWARD",
        )
        # Redis en ECS: permitir port 6379 dentro del mismo SG.
        self.service_security_group.add_ingress_rule(
            peer=self.service_security_group,
            connection=ec2.Port.tcp(6379),
            description="Redis service discovery entre tasks SWARD",
        )

        # Ingress en SG de RDS desde el SG de ECS.
        if db_security_group is not None:
            ec2.CfnSecurityGroupIngress(
                self,
                "RdsIngressFromEcs",
                group_id=db_security_group.security_group_id,
                ip_protocol="tcp",
                from_port=5432,
                to_port=5432,
                source_security_group_id=self.service_security_group.security_group_id,
                description="Permitir PostgreSQL desde ECS",
            )

        # --- Application Load Balancer público ---
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "SwardAlb",
            vpc=vpc,
            internet_facing=True,
            load_balancer_name="sward-alb",
        )

        # TODO(ACM): cuando exista un certificado ACM + dominio, cambiar a
        # protocol=HTTPS, port=443, certificates=[cert] y redirigir 80 -> 443.
        # Por ahora el listener es HTTP:80 para poder sintetizar/desplegar sin
        # certificado.
        self.listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            open=True,
            default_action=elbv2.ListenerAction.fixed_response(
                404,
                content_type="application/json",
                message_body='{"error":"ruta no encontrada"}',
            ),
        )

        # Log group compartido (un stream prefix por servicio).
        log_group = logs.LogGroup(
            self,
            "SwardEcsLogs",
            log_group_name="/ecs/sward",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- Redis en ECS (se apaga junto con ECS, $0 cuando stopped) --------
        redis_task_def = ecs.FargateTaskDefinition(
            self,
            "TaskRedis",
            cpu=256,
            memory_limit_mib=512,
            family="sward-redis",
        )
        redis_container = redis_task_def.add_container(
            "ContainerRedis",
            container_name="redis",
            image=ecs.ContainerImage.from_registry(
                "public.ecr.aws/docker/library/redis:7-alpine"
            ),
            logging=ecs.LogDriver.aws_logs(stream_prefix="redis", log_group=log_group),
        )
        redis_container.add_port_mappings(
            ecs.PortMapping(container_port=6379, protocol=ecs.Protocol.TCP)
        )
        redis_service = ecs.FargateService(
            self,
            "ServiceRedis",
            cluster=self.cluster,
            task_definition=redis_task_def,
            desired_count=1,
            service_name="redis",
            min_healthy_percent=0,
            security_groups=[self.service_security_group],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            cloud_map_options=ecs.CloudMapOptions(
                name="redis",
                dns_record_type=servicediscovery.DnsRecordType.A,
                dns_ttl=Duration.seconds(30),
            ),
            capacity_provider_strategies=(
                [
                    ecs.CapacityProviderStrategy(
                        capacity_provider="FARGATE_SPOT",
                        weight=1,
                    )
                ]
                if is_dev
                else None
            ),
        )

        self.services: dict[str, ecs.FargateService] = {}

        for name, cfg in SERVICES.items():
            logical_id = name.replace("-", " ").title().replace(" ", "")

            task_def = ecs.FargateTaskDefinition(
                self,
                f"Task{logical_id}",
                cpu=256,
                memory_limit_mib=512,
                family=f"sward-{name}",
            )

            # ---- Variables de entorno (no sensibles) ----
            environment: dict[str, str] = {
                "ENVIRONMENT": "production",
                "AWS_REGION": self.region,
                "EVENTBRIDGE_BUS_NAME": event_bus_name,
                "CORS_ALLOWED_ORIGINS": '["https://sward-upc.github.io","http://localhost:5173"]',
            }
            # URLs internas de los demás microservicios vía Cloud Map.
            for other in SERVICES:
                env_key = f"{other.replace('-', '_').upper()}_SERVICE_URL"
                environment[env_key] = (
                    f"http://{other}.{self.namespace.namespace_name}:{CONTAINER_PORT}"
                )
            # Aliases cortos requeridos por algunos settings.py.
            environment["LMS_SERVICE_URL"] = environment["INTEGRACION_LMS_SERVICE_URL"]
            environment["CURSOS_SERVICE_URL"] = environment[
                "CURSOS_RECURSOS_SERVICE_URL"
            ]

            db = db_instances.get(name)
            if db is not None:
                environment["DATABASE_HOST"] = db.db_instance_endpoint_address
                environment["DATABASE_PORT"] = db.db_instance_endpoint_port
                # Dev: 1 RDS compartida → todos apuntan a la misma database.
                # Prod: cada servicio tiene su propia database.
                environment["DATABASE_NAME"] = (
                    "sward" if is_dev else f"sward_{name.replace('-', '_')}"
                )

            # Redis en ECS, accesible vía Cloud Map: redis.sward.local:6379
            if name in ("xai", "usuarios"):
                environment["REDIS_URL"] = (
                    f"redis://redis.{self.namespace.namespace_name}:6379/0"
                )

            if name == "integracion-lms":
                environment["MOODLE_MOCK"] = "false"

            # ms-usuarios consulta a integracion-lms en el registro real (rol,
            # nombre y moodle_user_id vienen de Moodle). Sin esto cae al mock.
            if name == "usuarios":
                environment["USE_MOCK_LMS"] = "false"

            # Modelo SAKT que descarga ms-recomendacion (cambiable sin rebuild de
            # imagen). Apunta al modelo entrenado sobre conceptos de Moodle.
            if name == "recomendacion":
                environment["SAKT_MODEL_S3_KEY"] = "sakt/moodle/model.pth"

            # Todos los servicios con event publisher necesitan PutEvents.
            if name in (
                "integracion-lms",
                "usuarios",
                "trazabilidad",
                "cursos-recursos",
                "recomendacion",
            ):
                task_def.task_role.add_to_principal_policy(
                    iam.PolicyStatement(
                        actions=["events:PutEvents"],
                        resources=[
                            f"arn:aws:events:{self.region}:{self.account}:event-bus/{event_bus_name}"
                        ],
                    )
                )

            # Permisos S3 para ms-recomendacion (descarga del modelo SAKT al arrancar).
            if name == "recomendacion" and models_bucket is not None:
                models_bucket.grant_read(task_def.task_role)

            # ---- Secretos (Secrets Manager) ----
            secret_env: dict[str, ecs.Secret] = {}
            cred = (db_credentials or {}).get(name)
            if cred is not None:
                secret_env["DB_USERNAME"] = ecs.Secret.from_secrets_manager(
                    cred, "username"
                )
                secret_env["DB_PASSWORD"] = ecs.Secret.from_secrets_manager(
                    cred, "password"
                )
            if jwt_secret is not None:
                secret_env["SECRET_KEY"] = ecs.Secret.from_secrets_manager(
                    jwt_secret, "secret_key"
                )
            sk = service_keys.get(name)
            if sk is not None:
                secret_env["SERVICE_KEY"] = ecs.Secret.from_secrets_manager(
                    sk, "service_key"
                )
                # ms-usuarios usa su propia SERVICE_KEY como X-Service-Key al
                # llamar a integracion-lms (que la valida vía AUTHORIZED_USUARIOS_KEY).
                if name == "usuarios":
                    secret_env["LMS_SERVICE_KEY"] = ecs.Secret.from_secrets_manager(
                        sk, "service_key"
                    )
            if name == "integracion-lms" and moodle_token is not None:
                secret_env["MOODLE_TOKEN"] = ecs.Secret.from_secrets_manager(
                    moodle_token, "moodle_token"
                )
                secret_env["MOODLE_BASE_URL"] = ecs.Secret.from_secrets_manager(
                    moodle_token, "moodle_base_url"
                )
            if name == "usuarios" and admin_seed_secret is not None:
                secret_env["ADMIN_SEED_PASSWORD"] = ecs.Secret.from_secrets_manager(
                    admin_seed_secret, "admin_seed_password"
                )

            # Inyecta la SERVICE_KEY de cada caller autorizado como ECS Secret.
            # El container la recibe como AUTHORIZED_<CALLER>_KEY en texto plano
            # (ECS resuelve el secreto antes de arrancar el container).
            for caller in AUTHORIZED_CALLERS.get(name, []):
                caller_sk = (service_keys or {}).get(caller)
                if caller_sk is not None:
                    env_key = f"AUTHORIZED_{caller.replace('-', '_').upper()}_KEY"
                    secret_env[env_key] = ecs.Secret.from_secrets_manager(
                        caller_sk, "service_key"
                    )

            container = task_def.add_container(
                f"Container{logical_id}",
                container_name=name,
                image=ecs.ContainerImage.from_registry(
                    f"ghcr.io/sward-upc/sward-ms-{name}:latest"
                ),
                environment=environment,
                secrets=secret_env,
                logging=ecs.LogDriver.aws_logs(stream_prefix=name, log_group=log_group),
            )
            container.add_port_mappings(
                ecs.PortMapping(
                    container_port=CONTAINER_PORT, protocol=ecs.Protocol.TCP
                )
            )

            service = ecs.FargateService(
                self,
                f"Service{logical_id}",
                cluster=self.cluster,
                task_definition=task_def,
                desired_count=1,
                service_name=name,
                min_healthy_percent=100,
                # Rollback automático si las tasks no arrancan (despliegue rápido).
                circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
                security_groups=[self.service_security_group],
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                # Service discovery interno (Cloud Map): <name>.sward.local
                cloud_map_options=ecs.CloudMapOptions(
                    name=name,
                    dns_record_type=servicediscovery.DnsRecordType.A,
                    dns_ttl=Duration.seconds(30),
                ),
                # Dev: Fargate Spot (~40% del precio on-demand).
                # Prod: on-demand (capacity_provider_strategies=None → FARGATE por defecto).
                capacity_provider_strategies=(
                    [
                        ecs.CapacityProviderStrategy(
                            capacity_provider="FARGATE_SPOT",
                            weight=1,
                        )
                    ]
                    if is_dev
                    else None
                ),
            )
            # Redis debe existir antes que los microservicios intenten arrancar
            # para que redis.sward.local resuelva vía Cloud Map desde el inicio.
            service.node.add_dependency(redis_service)
            self.services[name] = service

            # ---- Target group + regla de path-based routing en el ALB ----
            target_group = elbv2.ApplicationTargetGroup(
                self,
                f"Tg{logical_id}",
                vpc=vpc,
                port=CONTAINER_PORT,
                protocol=elbv2.ApplicationProtocol.HTTP,
                target_type=elbv2.TargetType.IP,
                targets=[service],
                health_check=elbv2.HealthCheck(
                    path="/health",
                    healthy_http_codes="200",
                    interval=Duration.seconds(30),
                    timeout=Duration.seconds(5),
                ),
            )
            self.listener.add_target_groups(
                f"Rule{logical_id}",
                priority=cfg["priority"],
                conditions=[elbv2.ListenerCondition.path_patterns(cfg["paths"])],
                target_groups=[target_group],
            )
