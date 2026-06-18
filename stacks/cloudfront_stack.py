from aws_cdk import (
    CfnOutput,
    Duration,
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
      * ResponseHeadersPolicy CORS — permite que el portal Scalar en GitHub Pages
        haga fetch de los openapi.json sin tocar los microservicios.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        alb: elbv2.ApplicationLoadBalancer,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Reescribe /api/v1/<path> → /<path> y resuelve preflight CORS en el edge.
        # El preflight OPTIONS nunca llega al backend (evita el 400 de Starlette
        # cuando el origin no está en su lista de allow_origins).
        strip_prefix_fn = cloudfront.Function(
            self,
            "StripApiV1Prefix",
            function_name="sward-strip-api-v1",
            code=cloudfront.FunctionCode.from_inline(
                "var ALLOWED_ORIGINS = ['https://sward-upc.github.io', 'http://localhost:5173'];"
                "\nfunction handler(event) {"
                "\n    var request = event.request;"
                "\n    var uri = request.uri;"
                "\n    if (uri === '/api/v1' || uri.startsWith('/api/v1/')) {"
                "\n        request.uri = uri.slice('/api/v1'.length) || '/';"
                "\n    }"
                "\n    if (request.method === 'OPTIONS') {"
                "\n        var origin = (request.headers['origin'] || {}).value || '';"
                "\n        if (ALLOWED_ORIGINS.indexOf(origin) !== -1) {"
                "\n            return {"
                "\n                statusCode: 204,"
                "\n                statusDescription: 'No Content',"
                "\n                headers: {"
                "\n                    'access-control-allow-origin': { value: origin },"
                "\n                    'access-control-allow-methods': { value: 'GET,POST,PUT,DELETE,PATCH,OPTIONS,HEAD' },"
                "\n                    'access-control-allow-headers': { value: 'Authorization,Content-Type' },"
                "\n                    'access-control-max-age': { value: '600' }"
                "\n                }"
                "\n            };"
                "\n        }"
                "\n    }"
                "\n    return request;"
                "\n}"
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        # CORS para el portal Scalar en GitHub Pages.
        # Se gestiona aquí (gateway) para no modificar ningún microservicio.
        cors_policy = cloudfront.ResponseHeadersPolicy(
            self,
            "SwardCorsPolicy",
            response_headers_policy_name="sward-cors-api",
            cors_behavior=cloudfront.ResponseHeadersCorsBehavior(
                access_control_allow_credentials=False,
                access_control_allow_headers=["*"],
                access_control_allow_methods=[
                    "GET",
                    "POST",
                    "PUT",
                    "DELETE",
                    "PATCH",
                    "OPTIONS",
                    "HEAD",
                ],
                access_control_allow_origins=["https://sward-upc.github.io", "http://localhost:5173"],
                access_control_max_age=Duration.seconds(600),
                origin_override=True,
            ),
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
                response_headers_policy=cors_policy,
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
