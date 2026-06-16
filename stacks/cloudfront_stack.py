from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class CloudfrontStack(Stack):
    """CloudFront distribution delante del ALB — provee HTTPS sin dominio propio.

    Flujo:
      cliente ──HTTPS──► CloudFront (*.cloudfront.net) ──HTTP──► ALB (interno AWS)

    CloudFront termina TLS; la comunicación CloudFront→ALB es HTTP dentro de la
    red de AWS (equivale a un túnel interno, no viaja por internet público).

    Configuración:
      * Cache deshabilitado — la API REST nunca debe cachearse.
      * AllowedMethods.ALLOW_ALL — soporta GET/POST/PUT/DELETE/PATCH.
      * ALL_VIEWER_EXCEPT_HOST_HEADER — reenvía todos los headers (incluido
        Authorization con el JWT) excepto Host (para que ALB use su propio dominio).
      * REDIRECT_TO_HTTPS — fuerza HTTPS en el viewer, HTTP en el origin.
      * CloudFront Function (viewer-request) — reescribe /api/v1/* → /* para que
        los microservicios no necesiten manejar el prefijo de versión.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        alb: elbv2.ApplicationLoadBalancer,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Reescribe /api/v1/<path> → /<path> antes de llegar al ALB.
        # Los servicios internos siguen usando sus rutas sin prefijo de versión.
        strip_prefix_fn = cloudfront.Function(
            self,
            "StripApiV1Prefix",
            function_name="sward-strip-api-v1",
            code=cloudfront.FunctionCode.from_inline(
                """
function handler(event) {
    var request = event.request;
    var uri = request.uri;
    if (uri === '/api/v1' || uri.startsWith('/api/v1/')) {
        request.uri = uri.slice('/api/v1'.length) || '/';
    }
    return request;
}
""".strip()
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        distribution = cloudfront.Distribution(
            self,
            "SwardDistribution",
            comment="SWARD API — distribución CloudFront HTTPS",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    alb,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    http_port=80,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=strip_prefix_fn,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
        )

        self.api_url = f"https://{distribution.distribution_domain_name}"

        CfnOutput(
            self,
            "ApiUrl",
            value=self.api_url,
            description="URL pública HTTPS del API SWARD (prefijo /api/v1 reescrito en edge)",
            export_name="SwardApiUrl",
        )
