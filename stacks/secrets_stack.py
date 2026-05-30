from aws_cdk import Stack, RemovalPolicy, aws_secretsmanager as secrets
from constructs import Construct

# Microservicios que requieren una clave de servicio (service-to-service auth).
MICROSERVICES = [
    "usuarios",
    "integracion-lms",
    "trazabilidad",
    "cursos-recursos",
    "recomendacion",
    "xai",
]


class SecretsStack(Stack):
    """Secrets gestionados en AWS Secrets Manager.

    Centraliza los valores sensibles para que las task definitions de ECS los
    inyecten en tiempo de ejecución (nunca hardcodeados en el código ni en las
    variables de entorno en texto plano).

    Secrets definidos:
      * ``jwt_secret``       — SECRET_KEY compartida para firmar/validar JWT.
      * ``service_keys``     — clave SERVICE_KEY por microservicio (s2s auth).
      * ``moodle_token``     — token de API de Moodle (ms-integracion-lms).

    Las credenciales de RDS las gestiona ``DatabaseStack`` vía
    ``rds.Credentials.from_generated_secret`` (un secret por instancia), por lo
    que no se duplican aquí.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # SECRET_KEY para JWT — compartida por todos los microservicios que
        # validan tokens emitidos por ms-usuarios.
        self.jwt_secret = secrets.Secret(
            self,
            "JwtSecret",
            secret_name="sward/jwt-secret",
            description="SECRET_KEY compartida para firmar y validar JWT (HS256)",
            generate_secret_string=secrets.SecretStringGenerator(
                # Genera un JSON {"secret_key": "<random>"}.
                secret_string_template='{"jwt_algorithm": "HS256"}',
                generate_string_key="secret_key",
                password_length=64,
                exclude_punctuation=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # SERVICE_KEY por microservicio para autenticación service-to-service.
        self.service_keys: dict[str, secrets.Secret] = {}
        for service in MICROSERVICES:
            logical_id = service.replace("-", " ").title().replace(" ", "")
            self.service_keys[service] = secrets.Secret(
                self,
                f"ServiceKey{logical_id}",
                secret_name=f"sward/service-key/{service}",
                description=f"SERVICE_KEY para autenticación s2s de ms-{service}",
                generate_secret_string=secrets.SecretStringGenerator(
                    generate_string_key="service_key",
                    secret_string_template="{}",
                    password_length=48,
                    exclude_punctuation=True,
                ),
                removal_policy=RemovalPolicy.DESTROY,
            )

        # Token de API de Moodle para ms-integracion-lms. Valor real se rellena
        # manualmente tras el deploy (placeholder generado).
        self.moodle_token = secrets.Secret(
            self,
            "MoodleToken",
            secret_name="sward/moodle-token",
            description="Token de API de Moodle (rellenar manualmente tras deploy)",
            generate_secret_string=secrets.SecretStringGenerator(
                generate_string_key="moodle_token",
                secret_string_template='{"moodle_base_url": "https://moodle.example.com"}',
                password_length=40,
                exclude_punctuation=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
