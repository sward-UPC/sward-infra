from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct


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

    El deploy del código real lo realiza el repo SAM de cada Lambda; aquí se
    define la infraestructura de eventos y un código placeholder.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        recursos_bucket_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

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

        def _ecr_image(name: str) -> lambda_.DockerImageCode:
            repo = ecr.Repository.from_repository_name(
                self, f"EcrLambda{name.replace('-','').title()}", f"sward/lambda-{name}"
            )
            return lambda_.DockerImageCode.from_ecr(repo, tag_or_digest="latest")

        self.functions: dict[str, lambda_.DockerImageFunction] = {}

        # 1) lambda-interacciones <- SQS (alimentada por EventBridge).
        fn_interacciones = lambda_.DockerImageFunction(
            self,
            "LambdaInteracciones",
            function_name="sward-lambda-interacciones",
            code=_ecr_image("interacciones"),
            timeout=Duration.seconds(60),
            environment=common_env,
        )
        fn_interacciones.add_event_source(
            lambda_events.SqsEventSource(self.interacciones_queue, batch_size=10)
        )
        self.functions["interacciones"] = fn_interacciones

        # 2) lambda-alertas <- EventBridge (RecomendacionGenerada).
        fn_alertas = lambda_.DockerImageFunction(
            self,
            "LambdaAlertas",
            function_name="sward-lambda-alertas",
            code=_ecr_image("alertas"),
            timeout=Duration.seconds(60),
            environment=common_env,
        )
        self.functions["alertas"] = fn_alertas

        # 3) lambda-moodle-sync <- schedule cada 15 min.
        fn_moodle = lambda_.DockerImageFunction(
            self,
            "LambdaMoodleSync",
            function_name="sward-lambda-moodle-sync",
            code=_ecr_image("moodle-sync"),
            timeout=Duration.seconds(60),
            environment=common_env,
        )
        self.functions["moodle-sync"] = fn_moodle

        # 4) lambda-recursos <- S3 ObjectCreated.
        fn_recursos = lambda_.DockerImageFunction(
            self,
            "LambdaRecursos",
            function_name="sward-lambda-recursos",
            code=_ecr_image("recursos"),
            timeout=Duration.seconds(60),
            environment=common_env,
        )
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
        # no se forme un ciclo entre stacks. La notificación inyecta el ARN de la
        # Lambda en el bucket; el grant_read se resuelve contra el ARN derivado
        # del nombre, sin token cruzado.
        if recursos_bucket_name is not None:
            recursos_bucket = s3.Bucket.from_bucket_name(
                self, "RecursosBucketRef", recursos_bucket_name
            )
            recursos_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.LambdaDestination(fn_recursos),
            )
            recursos_bucket.grant_read(fn_recursos)
