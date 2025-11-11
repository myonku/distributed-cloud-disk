from redis.asyncio import Redis, from_url

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



