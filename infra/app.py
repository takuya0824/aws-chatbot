#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra_stack import ChatbotStack

app = cdk.App()

ChatbotStack(
    app,
    "AwsChatbotStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "ap-northeast-1"),
    ),
)

app.synth()
