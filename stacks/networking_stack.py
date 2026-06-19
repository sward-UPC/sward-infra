from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # NAT Instance t3.nano (~$3.50/mes) reemplaza NAT Gateway (~$32/mes).
        nat_provider = ec2.NatProvider.instance_v2(
            instance_type=ec2.InstanceType("t3.nano"),
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
