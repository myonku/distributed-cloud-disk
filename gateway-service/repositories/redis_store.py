import time
from datetime import datetime
from msgspec import json
from redis.asyncio import Redis, from_url

from models.models import GatewaySession, HandshakeTicket
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


class GatewaySessionService:
    """网关中转会话服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "gw:sess"

    def _key(self, sid: str) -> str:
        return f"{self.prefix}:{sid}"

    async def set_session(self, session: GatewaySession) -> bool:
        """存储网关中转会话"""
        client = self._rm.get_client()
        # 兼容 datetime 对象
        if isinstance(session.expires_at, datetime):
            ttl_seconds = int(session.expires_at.timestamp() - time.time())
        else:
            # 如果你未来把 expires_at 改成数值时间戳
            ttl_seconds = int(session.expires_at - time.time())
        ttl = max(ttl_seconds, 1)
        return await client.set(self._key(str(session.id)), json.encode(session), ex=ttl)

    async def get_session(self, session_id: str) -> GatewaySession | None:
        """获取网关中转会话"""
        client = self._rm.get_client()
        raw = await client.get(self._key(session_id))
        return json.decode(raw, type=GatewaySession) if raw else None

    async def delete_session(self, session_id: str) -> bool:
        """删除网关中转会话"""
        client = self._rm.get_client()
        return (await client.delete(self._key(session_id))) > 0

    async def ttl(self, session_id: str) -> int:
        """获取会话剩余存活时间，单位秒"""
        client = self._rm.get_client()
        return await client.ttl(self._key(session_id))


class HandshakeTicketService:
    """握手票据服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "gw:ticket"

    def _key(self, tid: str) -> str:
        return f"{self.prefix}:{tid}"

    async def set_ticket(self, ticket: HandshakeTicket) -> bool:
        """存储握手票据"""
        client = self._rm.get_client()
        if isinstance(ticket.expires_at, datetime):
            ttl_seconds = int(ticket.expires_at.timestamp() - time.time())
        else:
            ttl_seconds = int(ticket.expires_at - time.time())
        ttl = max(ttl_seconds, 1)
        return await client.set(self._key(str(ticket.id)), json.encode(ticket), ex=ttl)

    async def pop_ticket(self, ticket_id: str) -> HandshakeTicket | None:
        """获取并删除握手票据"""
        client = self._rm.get_client()
        key = self._key(ticket_id)
        pipe = client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw, _ = await pipe.execute()
        return json.decode(raw, type=HandshakeTicket) if raw else None

    async def ttl(self, ticket_id: str) -> int:
        """获取握手票据剩余存活时间，单位秒"""
        client = self._rm.get_client()
        return await client.ttl(self._key(ticket_id))
