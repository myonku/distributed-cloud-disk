from repositories.etcd_client import EtcdAsyncClient
from registry_service import LocalRegistry
from utils.selector_policy import (
    pick_hash_affinity,
    filter_by_tags,
    random_weighted,
)


class DiscoveryAdapter:
    """服务发现"""
    def __init__(self, client: EtcdAsyncClient):
        self.client = client
        self.registry = LocalRegistry(self.client)

    async def start(self, service_names: list[str]):
        """启动服务发现，预加载并监听指定服务的实例变更"""
        for name in service_names:
            await self.registry.prime_and_watch(name)

    def choose_endpoint(
        self, service_name: str, affinity_key: str | None, require_tags: list[str]
    ) -> str | None:
        """选择服务实例的 endpoint"""
        insts = self.registry.get_instances(service_name)
        insts = filter_by_tags(insts, require_tags)
        if not insts:
            return None
        if affinity_key:
            chosen = pick_hash_affinity(insts, affinity_key)
        else:
            chosen = random_weighted(insts)
        return chosen.endpoint if chosen else None

