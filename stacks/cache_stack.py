from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
)
from constructs import Construct


class CacheStack(Stack):
    """ElastiCache Redis para ms-xai (cache de explicaciones / pesos de atención).

    Se despliega en las subnets aisladas de la VPC y solo acepta tráfico desde
    el security group de ECS (inyectado por ``ServicesStack`` vía
    ``allow_ingress_from``). El endpoint se expone como ``redis_endpoint`` para
    construir ``REDIS_URL`` en la task definition de xai.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = vpc
        self.port = 6379

        # Security group del cluster Redis. El ingress lo abre ServicesStack
        # una vez que conoce el SG de ECS (allow_ingress_from).
        self.security_group = ec2.SecurityGroup(
            self,
            "RedisSecurityGroup",
            vpc=vpc,
            description="SG de ElastiCache Redis para ms-xai",
            allow_all_outbound=False,
        )

        # Subnet group con las subnets aisladas (privadas sin egress).
        private_subnets = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
        )
        subnet_group = elasticache.CfnSubnetGroup(
            self,
            "RedisSubnetGroup",
            description="Subnets privadas para ElastiCache Redis (ms-xai)",
            subnet_ids=private_subnets.subnet_ids,
            cache_subnet_group_name="sward-redis-subnets",
        )

        # Cluster Redis de un solo nodo (suficiente para cache de xai en demo).
        self.redis = elasticache.CfnCacheCluster(
            self,
            "RedisXai",
            cluster_name="sward-redis-xai",
            engine="redis",
            cache_node_type="cache.t3.micro",
            num_cache_nodes=1,
            port=self.port,
            vpc_security_group_ids=[self.security_group.security_group_id],
            cache_subnet_group_name=subnet_group.ref,
        )
        self.redis.add_dependency(subnet_group)

        # Nota: el ingress (Redis desde el SG de ECS) lo abre ServicesStack
        # sobre ``self.security_group`` para evitar una dependencia circular.

    @property
    def redis_endpoint(self) -> str:
        """Hostname del endpoint Redis (atributo de CloudFormation)."""
        return self.redis.attr_redis_endpoint_address
