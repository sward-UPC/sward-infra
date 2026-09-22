from aws_cdk import Stack, RemovalPolicy, aws_s3 as s3
from constructs import Construct


def nombre_bucket_recursos(cuenta: str) -> str:
    return f"sward-recursos-educativos-{cuenta}"


def nombre_bucket_modelos(cuenta: str) -> str:
    return f"sward-models-{cuenta}"


class StorageStack(Stack):
    """Buckets de material y de modelos.

    Los nombres de bucket son únicos en todo AWS: `sward-recursos-educativos` y
    `sward-models` pertenecen a otra cuenta (la del equipo anterior), así que
    llevan el id de la cuenta como sufijo. Se conservan al destruir el stack
    (RETAIN): este stack no se destruye entre pruebas.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.recursos_bucket = s3.Bucket(
            self,
            "SwardRecursosBucket",
            bucket_name=nombre_bucket_recursos(self.account),
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.models_bucket = s3.Bucket(
            self,
            "SwardModelsBucket",
            bucket_name=nombre_bucket_modelos(self.account),
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
