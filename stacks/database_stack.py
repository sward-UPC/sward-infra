from aws_cdk import Stack, RemovalPolicy, aws_ec2 as ec2, aws_rds as rds
from constructs import Construct

MICROSERVICES = [
    "usuarios",
    "integracion-lms",
    "trazabilidad",
    "cursos-recursos",
    "recomendacion",
    "xai",
]


class DatabaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.instances: dict[str, rds.DatabaseInstance] = {}

        for service in MICROSERVICES:
            logical_id = service.replace("-", "").capitalize()
            instance = rds.DatabaseInstance(
                self,
                f"Db{logical_id}",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_15
                ),
                instance_type=ec2.InstanceType.of(
                    ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
                ),
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                ),
                database_name=f"sward_{service.replace('-', '_')}",
                removal_policy=RemovalPolicy.DESTROY,
                deletion_protection=False,
            )
            self.instances[service] = instance
