from datetime import datetime
import time
from models.models import HandshakeTicket
from repositories.redis_store import RedisManager
from msgspec import json


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
