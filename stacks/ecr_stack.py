from aws_cdk import Stack, RemovalPolicy, aws_ecr as ecr
from constructs import Construct

# Las lambdas DEBEN tener sus imágenes en ECR (AWS no permite registries externos).
# Los microservicios ECS usan GHCR directamente (público, gratis).
LAMBDAS = [
    "moodle-sync",
    "interacciones",
    "alertas",
    "recursos",
    "notificaciones",
]

MAX_IMAGE_COUNT = 10


class EcrStack(Stack):
    """Repositorios ECR exclusivamente para las 4 lambdas.

    Los microservicios ECS usan GHCR (público) para ahorrar costos de ECR.
    Lambda no admite registries externos — las lambdas sí requieren ECR.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repositories: dict[str, ecr.Repository] = {}

        for name in LAMBDAS:
            logical_id = name.replace("-", " ").title().replace(" ", "")
            repo = ecr.Repository(
                self,
                f"EcrLambda{logical_id}",
                repository_name=f"sward/lambda-{name}",
                image_scan_on_push=True,
                image_tag_mutability=ecr.TagMutability.MUTABLE,
                removal_policy=RemovalPolicy.DESTROY,
                empty_on_delete=True,
                lifecycle_rules=[
                    ecr.LifecycleRule(
                        description=f"Conservar solo las últimas {MAX_IMAGE_COUNT} imágenes",
                        max_image_count=MAX_IMAGE_COUNT,
                        rule_priority=1,
                    )
                ],
            )
            self.repositories[name] = repo
