from aws_cdk import Stack, RemovalPolicy, aws_s3 as s3
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.recursos_bucket = s3.Bucket(
            self,
            "SwardRecursosBucket",
            bucket_name="sward-recursos-educativos",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.models_bucket = s3.Bucket(
            self,
            "SwardModelsBucket",
            bucket_name="sward-models",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
