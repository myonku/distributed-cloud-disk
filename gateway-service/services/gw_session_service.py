from datetime import datetime
import time
from models.models import GatewaySession
from repositories.redis_store import RedisManager
from msgspec import json


class GatewaySessionService:
    """网关会话服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "gw:sess"

    def _key(self, sid: str) -> str:
        return f"{self.prefix}:{sid}"

    async def set_session(self, session: GatewaySession) -> bool:
        """存储网关会话"""
        client = self._rm.get_client()
        # 兼容 datetime 对象
        if isinstance(session.expires_at, datetime):
            ttl_seconds = int(session.expires_at.timestamp() - time.time())
        else:
            ttl_seconds = int(session.expires_at - time.time())
        ttl = max(ttl_seconds, 1)
        return await client.set(
            self._key(str(session.id)), json.encode(session), ex=ttl
        )

    async def get_session(self, session_id: str) -> GatewaySession | None:
        """获取网关会话"""
        client = self._rm.get_client()
        raw = await client.get(self._key(session_id))
        return json.decode(raw, type=GatewaySession) if raw else None

    async def delete_session(self, session_id: str) -> bool:
        """删除网关会话"""
        client = self._rm.get_client()
        return (await client.delete(self._key(session_id))) > 0

    async def ttl(self, session_id: str) -> int:
        """获取会话剩余存活时间，单位秒"""
        client = self._rm.get_client()
        return await client.ttl(self._key(session_id))
