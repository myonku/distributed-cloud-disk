import time
from models.models import TemporaryHandshake
from repositories.redis_store import RedisManager
from msgspec import json


class TemporaryHandshakeService:
    """
    临时握手 DAO：用于存取临时握手状态
    """

    def __init__(self, redis: RedisManager):
        self.redis = redis
        self.prefix = "hs:metadata:tmp"

    def _key(self, sid: str) -> str:
        return f"{self.prefix}:{sid}"

    async def set(self, hs: TemporaryHandshake) -> bool:
        """存储临时握手状态"""
        client = self.redis.get_client()
        ttl = max(int(hs.expires_at - time.time()), 1)
        return await client.set(self._key(hs.id), json.encode(hs), ex=ttl)

    async def get(self, sid: str) -> TemporaryHandshake | None:
        """ "获取临时握手状态"""
        client = self.redis.get_client()
        raw = await client.get(self._key(sid))
        return json.decode(raw, type=TemporaryHandshake) if raw else None

    async def delete(self, sid: str) -> bool:
        """删除临时握手状态"""
        client = self.redis.get_client()
        return (await client.delete(self._key(sid))) > 0
