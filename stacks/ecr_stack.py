from aws_cdk import Stack, RemovalPolicy, aws_ecr as ecr
from constructs import Construct

# Microservicios SWARD. Cada uno tiene su propio repositorio ECR.
MICROSERVICES = [
    "usuarios",
    "integracion-lms",
    "trazabilidad",
    "cursos-recursos",
    "recomendacion",
    "xai",
]

# Número de imágenes a conservar por repositorio (lifecycle policy).
MAX_IMAGE_COUNT = 10


class EcrStack(Stack):
    """Repositorios ECR para las imágenes Docker de los microservicios.

    Un repositorio por microservicio, nombrado ``sward/<servicio>``.
    El pipeline de cada microservicio construye su imagen y la empuja aquí
    antes de que ECS Fargate la consuma.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repositories: dict[str, ecr.Repository] = {}

        for service in MICROSERVICES:
            logical_id = service.replace("-", " ").title().replace(" ", "")
            repo = ecr.Repository(
                self,
                f"Ecr{logical_id}",
                repository_name=f"sward/{service}",
                image_scan_on_push=True,
                image_tag_mutability=ecr.TagMutability.MUTABLE,
                # En sandbox/demo permitimos destruir el repo (incluyendo imágenes).
                removal_policy=RemovalPolicy.DESTROY,
                empty_on_delete=True,
                lifecycle_rules=[
                    ecr.LifecycleRule(
                        description=(
                            f"Conservar solo las últimas {MAX_IMAGE_COUNT} imágenes"
                        ),
                        max_image_count=MAX_IMAGE_COUNT,
                        rule_priority=1,
                    )
                ],
            )
            self.repositories[service] = repo
