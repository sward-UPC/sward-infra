#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.networking_stack import NetworkingStack
from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack
from stacks.services_stack import ServicesStack
from stacks.lambdas_stack import LambdasStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or "123456789012",
    region=app.node.try_get_context("region") or "us-east-1",
)

networking = NetworkingStack(app, "SwardNetworking", env=env)
storage = StorageStack(app, "SwardStorage", env=env)
database = DatabaseStack(app, "SwardDatabase", vpc=networking.vpc, env=env)
services = ServicesStack(app, "SwardServices", vpc=networking.vpc, env=env)
lambdas = LambdasStack(app, "SwardLambdas", vpc=networking.vpc, env=env)

app.synth()
