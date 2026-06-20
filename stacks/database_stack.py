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
    """RDS PostgreSQL para los 6 microservicios SWARD.

    Modo prod (is_dev=False, por defecto):
      6× RDS t3.micro — aislamiento completo, 1 instancia + 1 credencial por servicio.

    Modo dev (is_dev=True, cdk deploy -c dev=true):
      1× RDS t3.micro compartida — todos los servicios usan DATABASE_NAME="sward"
      y las mismas credenciales. Cada servicio crea sus propias tablas vía
      SQLAlchemy create_all(). Ahorro: ~$60/mes cuando está corriendo.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        *,
        is_dev: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.port = 5432
        self.is_dev = is_dev

        # Security group compartido por todas las instancias RDS.
        self.security_group = ec2.SecurityGroup(
            self,
            "RdsSecurityGroup",
            vpc=vpc,
            description="SG compartido de las instancias RDS PostgreSQL de SWARD",
            allow_all_outbound=False,
        )

        self.instances: dict[str, rds.DatabaseInstance] = {}

        _common = dict(
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
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
        )

        if is_dev:
            # 1 instancia compartida — todos los servicios conectan a database "sward".
            instance = rds.DatabaseInstance(
                self,
                "DbShared",
                **_common,
                credentials=rds.Credentials.from_generated_secret(
                    "sward_admin",
                    secret_name="sward/rds/shared",
                ),
                database_name="sward",
            )
            for service in MICROSERVICES:
                self.instances[service] = instance
        else:
            # 1 instancia por microservicio (aislamiento prod).
            for service in MICROSERVICES:
                logical_id = service.replace("-", "").capitalize()
                instance = rds.DatabaseInstance(
                    self,
                    f"Db{logical_id}",
                    **_common,
                    credentials=rds.Credentials.from_generated_secret(
                        f"sward_{service.replace('-', '_')}",
                        secret_name=f"sward/rds/{service}",
                    ),
                    database_name=f"sward_{service.replace('-', '_')}",
                )
                self.instances[service] = instance

        # Nota: el ingress (PostgreSQL desde el SG de ECS) lo abre ServicesStack
        # sobre ``self.security_group`` para evitar una dependencia circular
        # entre stacks (services ya depende de database).
