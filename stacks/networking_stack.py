from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # NAT Instance t3.micro (~$7.50/mes) reemplaza NAT Gateway (~$32/mes).
        # OUTBOUND_ONLY + ingreso desde el CIDR de la VPC (abajo): las subnets
        # privadas rutean a través de la NAT sin abrirla a internet. Antes se usaba
        # INBOUND_AND_OUTBOUND, que dejaba todos los puertos abiertos a 0.0.0.0/0.
        #
        # Era t3.nano hasta el 26 de septiembre de 2026. La cuenta está en el plan
        # gratuito de AWS, que sólo admite tipos elegibles para capa gratuita, y
        # t3.nano no lo es: EC2 devolvía «not eligible for Free Tier» y el stack
        # entero quedaba en ROLLBACK. t3.micro sí es elegible; cuesta unos 5 USD
        # más al mes y no cambia nada más del diseño.
        nat_provider = ec2.NatProvider.instance_v2(
            instance_type=ec2.InstanceType("t3.micro"),
            default_allowed_traffic=ec2.NatTrafficDirection.OUTBOUND_ONLY,
        )

        self.vpc = ec2.Vpc(
            self,
            "SwardVpc",
            max_azs=2,
            nat_gateways=1,
            nat_gateway_provider=nat_provider,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )
        nat_provider.connections.allow_from(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            ec2.Port.all_traffic(),
            "Trafico saliente de las subnets privadas",
        )
