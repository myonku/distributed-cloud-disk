import time
from models.models import UploadSessionCache
from repositories.redis_store import RedisManager
from msgspec import json


class UploadSessionService:
    """上传会话服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "md:upload"

    def _key(self, uid: str) -> str:
        return f"{self.prefix}:{uid}"

    async def set_upload(self, us: UploadSessionCache) -> bool:
        """设置上传会话"""
        client = self._rm.get_client()
        ttl = max(int(us.expires_at - time.time()), 1)
        return await client.set(self._key(us.id), json.encode(us), ex=ttl)

    async def get_upload(self, uid: str) -> UploadSessionCache | None:
        """获取上传会话"""
        client = self._rm.get_client()
        raw = await client.get(self._key(uid))
        return json.decode(raw, type=UploadSessionCache) if raw else None
