from aws_cdk import Stack, Duration, aws_ec2 as ec2, aws_events as events, aws_sqs as sqs
from constructs import Construct


class LambdasStack(Stack):
    """
    Skeleton para las 4 AWS Lambdas del sistema SWARD.
    Las funciones Lambda se implementarán en sus repos individuales.
    Este stack define los triggers (EventBridge, SQS) y la configuración.
    """

    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Bus de eventos central
        self.event_bus = events.EventBus(
            self,
            "SwardEventBus",
            event_bus_name="sward-event-bus",
        )

        # Cola SQS para procesamiento de interacciones
        self.interacciones_queue = sqs.Queue(
            self,
            "SwardInteraccionesQueue",
            queue_name="sward-interacciones",
            visibility_timeout=Duration.seconds(300),
        )
