from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_rds as rds,
)
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
    """6× RDS PostgreSQL, una instancia por microservicio.

    Cada instancia:
      * vive en las subnets aisladas de la VPC,
      * genera su credencial (usuario/clave) en Secrets Manager
        (``rds.Credentials.from_generated_secret``),
      * comparte un security group común al que ``ServicesStack`` abre ingress
        desde el SG de ECS vía ``allow_ingress_from``.

    Expone ``instances`` y ``credentials`` (secret por servicio) para que
    ServicesStack construya el ``DATABASE_URL`` de cada task definition.
    """

    def __init__(
        self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.port = 5432

        # Security group compartido por todas las instancias RDS.
        self.security_group = ec2.SecurityGroup(
            self,
            "RdsSecurityGroup",
            vpc=vpc,
            description="SG compartido de las instancias RDS PostgreSQL de SWARD",
            allow_all_outbound=False,
        )

        self.instances: dict[str, rds.DatabaseInstance] = {}

        for service in MICROSERVICES:
            logical_id = service.replace("-", "").capitalize()
            db_user = f"sward_{service.replace('-', '_')}"
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
                security_groups=[self.security_group],
                # Credencial generada en Secrets Manager (usuario + clave).
                credentials=rds.Credentials.from_generated_secret(
                    db_user,
                    secret_name=f"sward/rds/{service}",
                ),
                database_name=f"sward_{service.replace('-', '_')}",
                removal_policy=RemovalPolicy.DESTROY,
                deletion_protection=False,
            )
            self.instances[service] = instance

        # Nota: el ingress (PostgreSQL desde el SG de ECS) lo abre ServicesStack
        # sobre ``self.security_group`` para evitar una dependencia circular
        # entre stacks (services ya depende de database).
