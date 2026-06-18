#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.networking_stack import NetworkingStack
from stacks.ecr_stack import EcrStack
from stacks.secrets_stack import SecretsStack
from stacks.database_stack import DatabaseStack
from stacks.cache_stack import CacheStack
from stacks.storage_stack import StorageStack
from stacks.services_stack import ServicesStack
from stacks.lambdas_stack import LambdasStack
from stacks.cloudfront_stack import CloudfrontStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account")
    or os.environ.get("CDK_DEFAULT_ACCOUNT", "050451404093"),
    region=app.node.try_get_context("region")
    or os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Orden de dependencias: networking -> ecr/secrets/storage -> database/cache
# -> services -> lambdas.
networking = NetworkingStack(app, "SwardNetworking", env=env)

ecr = EcrStack(app, "SwardEcr", env=env)
secrets = SecretsStack(app, "SwardSecrets", env=env)
storage = StorageStack(app, "SwardStorage", env=env)

database = DatabaseStack(app, "SwardDatabase", vpc=networking.vpc, env=env)
cache = CacheStack(app, "SwardCache", vpc=networking.vpc, env=env)

_db_credentials = {name: inst.secret for name, inst in database.instances.items()}

services = ServicesStack(
    app,
    "SwardServices",
    vpc=networking.vpc,
    db_instances=database.instances,
    db_credentials=_db_credentials,
    db_security_group=database.security_group,
    redis_security_group=cache.security_group,
    redis_port=cache.port,
    jwt_secret=secrets.jwt_secret,
    service_keys=secrets.service_keys,
    moodle_token=secrets.moodle_token,
    admin_seed_secret=secrets.admin_seed_secret,
    redis_endpoint=cache.redis_endpoint,
    models_bucket=storage.models_bucket,
    env=env,
)

lambdas = LambdasStack(
    app,
    "SwardLambdas",
    vpc=networking.vpc,
    db_instances=database.instances,
    db_credentials=_db_credentials,
    db_security_group=database.security_group,
    ecs_security_group=services.service_security_group,
    # Nombre literal del bucket (definido en StorageStack) para evitar un token
    # cruzado entre stacks en la notificación S3 -> lambda-recursos.
    recursos_bucket_name="sward-recursos-educativos",
    env=env,
)

# Dependencias explícitas (algunas ya son implícitas por referencias cruzadas).
database.add_dependency(networking)
cache.add_dependency(networking)
services.add_dependency(ecr)
services.add_dependency(secrets)
services.add_dependency(database)
services.add_dependency(cache)
lambdas.add_dependency(database)
lambdas.add_dependency(services)
# Nota: no se declara lambdas.add_dependency(storage) porque la notificación
# S3 -> lambda-recursos hace que StorageStack dependa de LambdasStack (la
# dependencia fluye en sentido inverso, gestionada por CDK automáticamente).

cloudfront_dist = CloudfrontStack(
    app,
    "SwardCloudfront",
    alb=services.alb,
    env=env,
)
cloudfront_dist.add_dependency(services)

app.synth()
