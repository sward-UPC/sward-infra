from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct

_CORS_ORIGINS_JS = "['https://sward-upc.github.io','http://localhost:5173']"


class CloudfrontStack(Stack):
    """CloudFront distribution delante del ALB — provee HTTPS sin dominio propio.

    Flujo:
      cliente ──HTTPS──► CloudFront (*.cloudfront.net) ──HTTP──► ALB (interno AWS)

    CORS gestionado íntegramente con dos CloudFront Functions:
      * viewer-request  — reescribe /api/v1/* → /* y resuelve preflights OPTIONS
        directamente en el edge (204 + headers).
      * viewer-response — inyecta Access-Control-Allow-Origin en todas las
        respuestas reales que provienen del ALB.
    Se eliminó el ResponseHeadersPolicy porque no aplica sus headers CORS a
    respuestas generadas por Functions (FunctionGeneratedResponse).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        alb: elbv2.ApplicationLoadBalancer,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Viewer-request: strip /api/v1 prefix + manejar preflight OPTIONS en edge.
        viewer_request_fn = cloudfront.Function(
            self,
            "ViewerRequestFn",
            function_name="sward-viewer-request",
            code=cloudfront.FunctionCode.from_inline(
                f"var ALLOWED={_CORS_ORIGINS_JS};"
                "\nfunction handler(event){"
                "\n  var req=event.request,uri=req.uri;"
                "\n  if(uri==='/api/v1'||uri.startsWith('/api/v1/')){"
                "\n    req.uri=uri.slice('/api/v1'.length)||'/';"
                "\n  }"
                "\n  if(req.method==='OPTIONS'){"
                "\n    var orig=(req.headers['origin']||{}).value||'';"
                "\n    if(ALLOWED.indexOf(orig)!==-1){"
                "\n      return{"
                "\n        statusCode:204,statusDescription:'No Content',"
                "\n        headers:{"
                "\n          'access-control-allow-origin':{value:orig},"
                "\n          'access-control-allow-methods':{value:'GET,POST,PUT,DELETE,PATCH,OPTIONS,HEAD'},"
                "\n          'access-control-allow-headers':{value:'authorization,content-type'},"
                "\n          'access-control-max-age':{value:'600'},"
                "\n          'vary':{value:'Origin'}"
                "\n        }"
                "\n      };"
                "\n    }"
                "\n  }"
                "\n  return req;"
                "\n}"
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        # Viewer-response: inyecta CORS headers en respuestas reales del ALB.
        viewer_response_fn = cloudfront.Function(
            self,
            "ViewerResponseFn",
            function_name="sward-viewer-response",
            code=cloudfront.FunctionCode.from_inline(
                f"var ALLOWED={_CORS_ORIGINS_JS};"
                "\nfunction handler(event){"
                "\n  var req=event.request,resp=event.response;"
                "\n  var orig=(req.headers['origin']||{}).value||'';"
                "\n  if(ALLOWED.indexOf(orig)!==-1){"
                "\n    resp.headers['access-control-allow-origin']={value:orig};"
                "\n    resp.headers['vary']={value:'Origin'};"
                "\n  }"
                "\n  return resp;"
                "\n}"
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
                        function=viewer_request_fn,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    ),
                    cloudfront.FunctionAssociation(
                        function=viewer_response_fn,
                        event_type=cloudfront.FunctionEventType.VIEWER_RESPONSE,
                    ),
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
