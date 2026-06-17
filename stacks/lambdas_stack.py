from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct

# Nombre del namespace Cloud Map para resolver URLs internas.
CLOUD_MAP_NAMESPACE = "sward.local"
CONTAINER_PORT = 8000


class LambdasStack(Stack):
    """4× AWS Lambda + EventBridge rules + SQS (con DLQ).

    Lambdas y sus disparadores:
      * ``lambda-interacciones`` — consume la cola SQS alimentada por la regla
        EventBridge ``InteraccionRegistrada`` (patrón Event -> SQS -> Lambda con
        DLQ para reintentos).
      * ``lambda-alertas`` — disparada por la regla EventBridge
        ``RecomendacionGenerada``.
      * ``lambda-moodle-sync`` — disparada por un schedule cada 15 minutos.
      * ``lambda-recursos`` — disparada por ``ObjectCreated`` en el bucket de
        recursos educativos (S3).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        db_instances: dict | None = None,
        db_credentials: dict | None = None,
        db_security_group: ec2.ISecurityGroup | None = None,
        ecs_security_group: ec2.ISecurityGroup | None = None,
        recursos_bucket_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        db_instances = db_instances or {}
        db_credentials = db_credentials or {}

        # Security group compartido por las Lambda functions.
        self.lambda_security_group = ec2.SecurityGroup(
            self,
            "LambdaSecurityGroup",
            vpc=vpc,
            description="SG de las Lambda functions de SWARD",
            allow_all_outbound=True,
        )

        # Permitir que las Lambdas se conecten a los servicios ECS vía Cloud Map.
        if ecs_security_group is not None:
            ec2.CfnSecurityGroupIngress(
                self,
                "EcsIngressFromLambda",
                group_id=ecs_security_group.security_group_id,
                ip_protocol="tcp",
                from_port=8000,
                to_port=8000,
                source_security_group_id=self.lambda_security_group.security_group_id,
                description="Lambda SWARD -> ECS services (Cloud Map port 8000)",
            )

        # Permitir acceso a RDS desde las Lambdas.
        if db_security_group is not None:
            ec2.CfnSecurityGroupIngress(
                self,
                "RdsIngressFromLambda",
                group_id=db_security_group.security_group_id,
                ip_protocol="tcp",
                from_port=5432,
                to_port=5432,
                source_security_group_id=self.lambda_security_group.security_group_id,
                description="Permitir PostgreSQL desde Lambda",
            )

        vpc_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        # Bus de eventos central.
        self.event_bus = events.EventBus(
            self,
            "SwardEventBus",
            event_bus_name="sward-event-bus",
        )

        # --- SQS con DLQ para reintentos de procesamiento de interacciones ---
        self.interacciones_dlq = sqs.Queue(
            self,
            "SwardInteraccionesDlq",
            queue_name="sward-interacciones-dlq",
            retention_period=Duration.days(14),
        )
        self.interacciones_queue = sqs.Queue(
            self,
            "SwardInteraccionesQueue",
            queue_name="sward-interacciones",
            visibility_timeout=Duration.seconds(300),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.interacciones_dlq,
            ),
        )

        common_env = {
            "ENVIRONMENT": "production",
            "EVENTBRIDGE_BUS_NAME": self.event_bus.event_bus_name,
        }

        def _ecr_image(
            name: str,
        ) -> tuple[lambda_.DockerImageCode, ecr.IRepository]:
            repo = ecr.Repository.from_repository_name(
                self,
                f"EcrLambda{name.replace('-', '').title()}",
                f"sward/lambda-{name}",
            )
            return lambda_.DockerImageCode.from_ecr(repo, tag_or_digest="latest"), repo

        def _grant_ecr_pull(
            fn: lambda_.DockerImageFunction, repo: ecr.IRepository
        ) -> None:
            """Concede permisos de pull ECR al rol de la Lambda.

            grant_pull() otorga BatchCheckLayerAvailability/GetDownloadUrlForLayer/
            BatchGetImage sobre el repo. GetAuthorizationToken (recurso *) es
            necesario adicionalmente para que Lambda pueda autenticarse con ECR.
            """
            repo.grant_pull(fn)
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ecr:GetAuthorizationToken"],
                    resources=["*"],
                )
            )

        def _db_env(service: str) -> dict[str, str]:
            """Devuelve env vars de conexión a RDS para un servicio dado."""
            inst = db_instances.get(service)
            if inst is None:
                return {}
            return {
                "DATABASE_HOST": inst.db_instance_endpoint_address,
                "DATABASE_PORT": inst.db_instance_endpoint_port,
                "DATABASE_NAME": f"sward_{service.replace('-', '_')}",
            }

        def _grant_db_secret(fn: lambda_.DockerImageFunction, service: str) -> None:
            """Concede permisos de lectura del secret RDS a la Lambda."""
            cred = db_credentials.get(service)
            if cred is not None:
                cred.grant_read(fn)
                fn.add_environment("DB_SECRET_ARN", cred.secret_arn)

        self.functions: dict[str, lambda_.DockerImageFunction] = {}

        # 1) lambda-interacciones <- SQS (alimentada por EventBridge).
        _code_interacciones, _repo_interacciones = _ecr_image("interacciones")
        fn_interacciones = lambda_.DockerImageFunction(
            self,
            "LambdaInteracciones",
            function_name="sward-lambda-interacciones",
            code=_code_interacciones,
            timeout=Duration.seconds(60),
            vpc=vpc,
            vpc_subnets=vpc_subnets,
            security_groups=[self.lambda_security_group],
            environment={**common_env, **_db_env("trazabilidad")},
        )
        _grant_ecr_pull(fn_interacciones, _repo_interacciones)
        _grant_db_secret(fn_interacciones, "trazabilidad")
        fn_interacciones.add_event_source(
            lambda_events.SqsEventSource(self.interacciones_queue, batch_size=10)
        )
        self.functions["interacciones"] = fn_interacciones

        # 2) lambda-alertas <- EventBridge (RecomendacionGenerada).
        _code_alertas, _repo_alertas = _ecr_image("alertas")
        fn_alertas = lambda_.DockerImageFunction(
            self,
            "LambdaAlertas",
            function_name="sward-lambda-alertas",
            code=_code_alertas,
            timeout=Duration.seconds(60),
            vpc=vpc,
            vpc_subnets=vpc_subnets,
            security_groups=[self.lambda_security_group],
            environment=common_env,
        )
        # lambda-alertas usa dos bases de datos con nombres de env var distintos.
        trazabilidad_inst = db_instances.get("trazabilidad")
        xai_inst = db_instances.get("xai")
        if trazabilidad_inst is not None:
            fn_alertas.add_environment(
                "TRAZABILIDAD_DATABASE_HOST",
                trazabilidad_inst.db_instance_endpoint_address,
            )
            fn_alertas.add_environment(
                "TRAZABILIDAD_DATABASE_PORT",
                trazabilidad_inst.db_instance_endpoint_port,
            )
            fn_alertas.add_environment(
                "TRAZABILIDAD_DATABASE_NAME", "sward_trazabilidad"
            )
        if xai_inst is not None:
            fn_alertas.add_environment(
                "XAI_DATABASE_HOST", xai_inst.db_instance_endpoint_address
            )
            fn_alertas.add_environment(
                "XAI_DATABASE_PORT", xai_inst.db_instance_endpoint_port
            )
            fn_alertas.add_environment("XAI_DATABASE_NAME", "sward_xai")
        trazabilidad_cred = db_credentials.get("trazabilidad")
        xai_cred = db_credentials.get("xai")
        if trazabilidad_cred is not None:
            trazabilidad_cred.grant_read(fn_alertas)
            fn_alertas.add_environment(
                "TRAZABILIDAD_DB_SECRET_ARN", trazabilidad_cred.secret_arn
            )
        if xai_cred is not None:
            xai_cred.grant_read(fn_alertas)
            fn_alertas.add_environment("XAI_DB_SECRET_ARN", xai_cred.secret_arn)
        _grant_ecr_pull(fn_alertas, _repo_alertas)
        self.functions["alertas"] = fn_alertas

        # 3) lambda-moodle-sync <- schedule cada 15 min.
        _code_moodle, _repo_moodle = _ecr_image("moodle-sync")
        fn_moodle = lambda_.DockerImageFunction(
            self,
            "LambdaMoodleSync",
            function_name="sward-lambda-moodle-sync",
            code=_code_moodle,
            timeout=Duration.seconds(60),
            vpc=vpc,
            vpc_subnets=vpc_subnets,
            security_groups=[self.lambda_security_group],
            environment={
                **common_env,
                # Cloud Map DNS — resuelve dentro del VPC.
                "LMS_SERVICE_URL": (
                    f"http://integracion-lms.{CLOUD_MAP_NAMESPACE}:{CONTAINER_PORT}"
                ),
            },
        )
        _grant_ecr_pull(fn_moodle, _repo_moodle)
        self.functions["moodle-sync"] = fn_moodle

        # 4) lambda-recursos <- S3 ObjectCreated.
        _code_recursos, _repo_recursos = _ecr_image("recursos")
        fn_recursos = lambda_.DockerImageFunction(
            self,
            "LambdaRecursos",
            function_name="sward-lambda-recursos",
            code=_code_recursos,
            timeout=Duration.seconds(60),
            vpc=vpc,
            vpc_subnets=vpc_subnets,
            security_groups=[self.lambda_security_group],
            environment={**common_env, **_db_env("cursos-recursos")},
        )
        _grant_ecr_pull(fn_recursos, _repo_recursos)
        _grant_db_secret(fn_recursos, "cursos-recursos")
        self.functions["recursos"] = fn_recursos

        # ----------------------- EventBridge rules -----------------------
        # InteraccionRegistrada -> SQS -> lambda-interacciones
        events.Rule(
            self,
            "RuleInteraccionRegistrada",
            rule_name="sward-interaccion-registrada",
            event_bus=self.event_bus,
            event_pattern=events.EventPattern(
                source=["sward.trazabilidad"],
                detail_type=["InteraccionRegistrada"],
            ),
            targets=[
                targets.SqsQueue(
                    self.interacciones_queue,
                    dead_letter_queue=self.interacciones_dlq,
                )
            ],
        )

        # RecomendacionGenerada -> lambda-alertas
        events.Rule(
            self,
            "RuleRecomendacionGenerada",
            rule_name="sward-recomendacion-generada",
            event_bus=self.event_bus,
            event_pattern=events.EventPattern(
                source=["sward.recomendacion"],
                detail_type=["RecomendacionGenerada"],
            ),
            targets=[targets.LambdaFunction(fn_alertas)],
        )

        # Schedule cada 15 min -> lambda-moodle-sync
        events.Rule(
            self,
            "RuleMoodleSyncSchedule",
            rule_name="sward-moodle-sync-schedule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[targets.LambdaFunction(fn_moodle)],
        )

        # S3 ObjectCreated -> lambda-recursos.
        # Importamos el bucket por nombre (no por referencia cruzada de ARN) para
        # que la dependencia fluya en una sola dirección (Storage -> Lambdas) y
        # no se forme un ciclo entre stacks.
        if recursos_bucket_name is not None:
            recursos_bucket = s3.Bucket.from_bucket_name(
                self, "RecursosBucketRef", recursos_bucket_name
            )
            recursos_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.LambdaDestination(fn_recursos),
            )
            recursos_bucket.grant_read(fn_recursos)
