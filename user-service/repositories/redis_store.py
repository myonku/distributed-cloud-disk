import time
import msgspec
from redis.asyncio import Redis, from_url

from models.models import BackendSessionCache
from config import ProjectConfig


class RedisManager:
    """Redis 连接管理器"""

    def __init__(self):
        self.redis: Redis | None = None
        self.is_initialized: bool = False

    async def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            if self.redis is None:
                return False
            return await self.redis.connection_pool.get_connection("PING") is not None
        except Exception:
            return False

    async def connect(self, config: ProjectConfig, **kwargs):
        """连接 Redis"""
        if not config.redis:
            raise ConnectionError("Redis配置初始化失败")
        print(f"正在连接Redis: {config.redis.redis_uri}")

        default_kwargs = {
            "encoding": "utf-8",
            "decode_responses": True,
            "max_connections": 20,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
        }
        default_kwargs.update(kwargs)

        self.redis = from_url(config.redis.redis_uri, **default_kwargs)
        self.is_initialized = True
        print("Redis连接完成")

    async def disconnect(self):
        """关闭连接"""
        if self.redis:
            print("正在关闭Redis连接")
            await self.redis.close()
            self.redis = None
            self.is_initialized = False

    def get_client(self) -> Redis:
        """获取 Redis 客户端"""
        if self.redis is None:
            raise RuntimeError("Redis未初始化")
        return self.redis


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
        return await client.set(self._key(sess.id), msgspec.json.encode(sess), ex=ttl)

    async def get_session(self, sid: str) -> BackendSessionCache | None:
        """获取会话"""
        client = self._rm.get_client()
        raw = await client.get(self._key(sid))
        return msgspec.json.decode(raw, type=BackendSessionCache) if raw else None
