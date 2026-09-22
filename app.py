#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.networking_stack import NetworkingStack
from stacks.ecr_stack import EcrStack
from stacks.secrets_stack import SecretsStack
from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack, nombre_bucket_recursos
from stacks.services_stack import ServicesStack
from stacks.lambdas_stack import LambdasStack
from stacks.cloudfront_stack import CloudfrontStack
from stacks.budget_stack import BudgetStack
from stacks.moodle_stack import MoodleStack

app = cdk.App()

# La cuenta ya no se fija en el codigo: sale del contexto (-c account=...) o de
# CDK_DEFAULT_ACCOUNT, que el CLI toma de las credenciales activas. Antes habia
# aqui la cuenta del integrante anterior, de modo que un despliegue distraido
# apuntaba a una cuenta ajena.
cuenta = app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
if not cuenta:
    raise SystemExit(
        "Falta la cuenta de AWS. Ejecuta con credenciales activas "
        "(aws configure / aws sso login) o pasa -c account=<id de tu cuenta>."
    )

env = cdk.Environment(
    account=cuenta,
    region=app.node.try_get_context("region")
    or os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Por defecto: modo dev (1 RDS compartida + Fargate Spot, ~$50/mes corriendo).
# Para prod completo: cdk deploy -c prod=true  (6 RDS separadas + Fargate on-demand).
is_dev = app.node.try_get_context("prod") != "true"

# Orden de dependencias: networking -> ecr/secrets/storage -> database
# -> services -> lambdas.
networking = NetworkingStack(app, "SwardNetworking", env=env)

ecr = EcrStack(app, "SwardEcr", env=env)
secrets = SecretsStack(app, "SwardSecrets", env=env)
storage = StorageStack(app, "SwardStorage", env=env)

database = DatabaseStack(
    app, "SwardDatabase", vpc=networking.vpc, is_dev=is_dev, env=env
)

_db_credentials = {name: inst.secret for name, inst in database.instances.items()}

services = ServicesStack(
    app,
    "SwardServices",
    vpc=networking.vpc,
    db_instances=database.instances,
    db_credentials=_db_credentials,
    db_security_group=database.security_group,
    jwt_secret=secrets.jwt_secret,
    service_keys=secrets.service_keys,
    moodle_token=secrets.moodle_token,
    admin_seed_secret=secrets.admin_seed_secret,
    youtube_api_key_secret=secrets.youtube_api_key,
    # Correo saliente de ms-usuarios. Gmail por defecto; otro proveedor con
    # -c smtp_host=... -c smtp_port=...
    smtp_secret=secrets.smtp,
    smtp_host=app.node.try_get_context("smtp_host") or "smtp.gmail.com",
    smtp_port=int(app.node.try_get_context("smtp_port") or 587),
    models_bucket=storage.models_bucket,
    is_dev=is_dev,
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
    recursos_bucket_name=nombre_bucket_recursos(cuenta),
    is_dev=is_dev,
    env=env,
)

# Dependencias explícitas (algunas ya son implícitas por referencias cruzadas).
database.add_dependency(networking)
services.add_dependency(ecr)
services.add_dependency(secrets)
services.add_dependency(database)
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

# Avisos de gasto. Los tres valores se pueden cambiar sin tocar el codigo:
#   cdk deploy SwardPresupuesto -c creditos=100 -c tope_mensual=50 \
#              -c correo_alertas=alguien@upc.edu.pe
BudgetStack(
    app,
    "SwardPresupuesto",
    correo_alertas=app.node.try_get_context("correo_alertas")
    or "u201616054@upc.edu.pe",
    creditos_usd=float(app.node.try_get_context("creditos") or 100),
    tope_mensual_usd=float(app.node.try_get_context("tope_mensual") or 50),
    env=env,
)

# Moodle en internet para los participantes externos del OE4. Queda fuera del
# apagado nocturno. Se despliega aparte:  cdk deploy SwardMoodle
moodle = MoodleStack(
    app,
    "SwardMoodle",
    vpc=networking.vpc,
    correo_admin=app.node.try_get_context("correo_admin_moodle")
    or "u201616054@upc.edu.pe",
    tipo_instancia=app.node.try_get_context("moodle_instancia") or "t3.small",
    env=env,
)
# Usa los secretos sward/smtp y sward/moodle-token, que crea SwardSecrets.
moodle.add_dependency(secrets)

app.synth()
