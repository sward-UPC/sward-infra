from aws_cdk import Stack, aws_ec2 as ec2, aws_apigateway as apigw
from constructs import Construct


class ServicesStack(Stack):
    """
    Skeleton para el API Gateway y los servicios de cómputo.
    Los microservicios se desplegarán como ECS Fargate tasks en una iteración posterior.
    """

    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # API Gateway REST API — punto de entrada para todos los microservicios
        self.api = apigw.RestApi(
            self,
            "SwardApiGateway",
            rest_api_name="sward-api",
            description="API Gateway del sistema SWARD",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
            ),
        )
