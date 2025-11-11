import time
from models.models import BackendSessionCache
from repositories.redis_store import RedisManager
from msgspec import json


class UserBackendSessionSevice:
    """用户后端会话数据访问服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "be:user:sess"

    def _key(self, sid: str) -> str:
        """生成存储键"""
        return f"{self.prefix}:{sid}"

    async def set_session(self, sess: BackendSessionCache) -> bool:
        """存储会话"""
        client = self._rm.get_client()
        ttl = max(int(sess.expires_at - time.time()), 1)
        return await client.set(self._key(sess.id), json.encode(sess), ex=ttl)

    async def get_session(self, sid: str) -> BackendSessionCache | None:
        """获取会话"""
        client = self._rm.get_client()
        raw = await client.get(self._key(sid))
        return json.decode(raw, type=BackendSessionCache) if raw else None

    async def refresh_claims(
        self, sid: str, roles: str, cred_level: int, claims_hash: str
    ) -> bool:
        """刷新会话"""
        client = self._rm.get_client()
        sess = await client.get(sid)
        if not sess:
            return False
        updated = BackendSessionCache(
            **{
                **sess.__dict__,
                "roles": roles,
                "cred_level": cred_level,
                "claims_hash": claims_hash,
                "claims_refreshed_at": time.time(),
            }
        )
        ttl = max(int(updated.expires_at - time.time()), 1)
        return await client.set(self._key(sess.id), json.encode(updated), ex=ttl)
