import asyncio
from msgspec import json
from collections.abc import Callable, Awaitable

from config import ProjectConfig
from models.models import ServiceInstance



class EtcdAsyncClient:
    """Etcd 异步客户端封装"""
    def __init__(self):
        self._client = None
        self._lease = None
        self.namespace = None

    async def connect(self, cfg: ProjectConfig):
        """
        TODO: 使用 etcd3aio.client(...) 连接
        留空实现以便在实际项目中替换为特定依赖。
        """
        # 示例：
        # import etcd3aio
        # kwargs = {}
        # if self.cfg.TLS_ENABLED:
        #     sslctx = ssl.create_default_context(cafile=self.cfg.CA_CERT) if self.cfg.CA_CERT else ssl.create_default_context()
        #     kwargs["ssl"] = sslctx
        # host, port = self.cfg.HOSTS[0].split(":")
        # self._client = await etcd3aio.client(host=host, port=int(port), user=self.cfg.USERNAME, password=self.cfg.PASSWORD, **kwargs)
        pass

    async def put_with_lease(self, key: str, value_bytes: bytes, ttl: int) -> None:
        """
        写入带租约（实例注册用），若无租约则创建，随后定时 keepalive
        """
        # TODO: 具体实现，示例接口：
        # if not self._lease:
        #     self._lease = await self._client.lease(ttl)
        # await self._client.put(key, value_bytes, lease=self._lease)
        pass

    async def keepalive_forever(self, ttl: int, stop_event: asyncio.Event):
        """
        周期性刷新租约
        """
        # while not stop_event.is_set():
        #     try:
        #         if self._lease:
        #             await self._lease.refresh()
        #     except Exception:
        #         pass
        #     await asyncio.sleep(ttl / 2)
        pass

    async def delete(self, key: str):
        # await self._client.delete(key)
        pass

    async def get_prefix(self, prefix: str) -> list[tuple[str, bytes]]:
        """
        列出前缀下的所有 KV
        """
        # resp = await self._client.get_prefix(prefix)
        # return [(kv.key.decode(), kv.value) for kv in resp.kvs]
        return []

    async def watch_prefix(
        self,
        prefix: str,
        callback: Callable[[str, bytes | None], Awaitable[None]],
        stop_event: asyncio.Event,
    ):
        """
        监听前缀，收到 put/delete 事件后回调：
          - put: value_bytes 为 bytes
          - delete: value_bytes 为 None
        """
        # 示例（伪代码）：
        # async for event in self._client.watch_prefix(prefix):
        #     if event.event_type == "put":
        #         await callback(event.key.decode(), event.value)
        #     elif event.event_type == "delete":
        #         await callback(event.key.decode(), None)
        #     if stop_event.is_set(): break
        pass


def build_service_key(ns: str, name: str, instance_id: str) -> str:
    """生成服务实例的 etcd 键"""
    return f"{ns}/services/{name}/{instance_id}"


def build_prefix(ns: str, name: str) -> str:
    """生成服务前缀"""
    return f"{ns}/services/{name}/"


def encode_instance(si: ServiceInstance) -> bytes:
    return json.encode(si)


def decode_instance(b: bytes) -> ServiceInstance:
    return json.decode(b, type=ServiceInstance)
