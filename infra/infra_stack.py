from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
)
from constructs import Construct

# Cheapest current-generation Claude model on Bedrock (Converse API).
# Claude Haiku 4.5 doesn't support on-demand invocation by the bare
# foundation-model ID in ap-northeast-1 — it must be invoked through the
# "JP" geo cross-region inference profile, which routes to Tokyo/Osaka.
BASE_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"
INFERENCE_PROFILE_ID = "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
JP_GEO_REGIONS = ["ap-northeast-1", "ap-northeast-3"]


class ChatbotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB: conversation history (pay-per-request, auto-expiring) ---
        table = dynamodb.Table(
            self,
            "ChatHistoryTable",
            partition_key=dynamodb.Attribute(
                name="session_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expire_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Lambda: chat handler (Bedrock Converse API + DynamoDB history) ---
        chat_fn = _lambda.Function(
            self,
            "ChatFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="app.handler",
            code=_lambda.Code.from_asset("../backend/lambda"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "TABLE_NAME": table.table_name,
                "MODEL_ID": INFERENCE_PROFILE_ID,
            },
        )
        table.grant_read_write_data(chat_fn)
        chat_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    # the inference profile itself, plus every foundation-model
                    # resource it may route the request to (JP geo: Tokyo/Osaka)
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{INFERENCE_PROFILE_ID}",
                    *[
                        f"arn:aws:bedrock:{r}::foundation-model/{BASE_MODEL_ID}"
                        for r in JP_GEO_REGIONS
                    ],
                ],
            )
        )
        # Anthropic models on Bedrock are AWS Marketplace products — the calling
        # principal needs these (non resource-scoped) actions to auto-subscribe
        # on first invocation.
        chat_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe",
                ],
                resources=["*"],
            )
        )

        # --- API Gateway (HTTP API — cheaper than REST API) ---
        http_api = apigwv2.HttpApi(
            self,
            "ChatApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["content-type"],
            ),
        )
        http_api.add_routes(
            path="/chat",
            methods=[apigwv2.HttpMethod.POST],
            integration=apigwv2_integrations.HttpLambdaIntegration(
                "ChatIntegration", chat_fn
            ),
        )

        # No auth on this API — throttle the default stage to bound cost.
        cfn_stage = http_api.default_stage.node.default_child
        cfn_stage.default_route_settings = apigwv2.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=20,
            throttling_rate_limit=10,
        )

        # --- S3 + CloudFront: static frontend ---
        site_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_200,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

        # Deploy the frontend assets plus a generated config.js carrying the
        # deploy-time API URL (unknown until the HttpApi is created above).
        s3_deployment.BucketDeployment(
            self,
            "FrontendDeployment",
            sources=[
                s3_deployment.Source.asset("../frontend"),
                s3_deployment.Source.data(
                    "config.js",
                    f"window.API_URL = '{http_api.api_endpoint}/chat';",
                ),
            ],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        CfnOutput(self, "SiteURL", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiURL", value=f"{http_api.api_endpoint}/chat")
        CfnOutput(self, "TableName", value=table.table_name)
