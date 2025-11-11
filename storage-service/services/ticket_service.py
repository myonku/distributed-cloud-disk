from models.models import HandshakeTicket
from repositories.redis_store import RedisManager
from msgspec import json


class TicketClient:
    """
    从网关键空间 pop 握手票据：gw:ticket:{ticket_id}
    """

    def __init__(self, redis: RedisManager):
        self.redis = redis
        self.prefix = "gw:ticket"

    def _key(self, tid: str) -> str:
        return f"{self.prefix}:{tid}"

    async def pop_ticket(self, ticket_id: str) -> HandshakeTicket | None:
        """消费握手票据"""
        client = self.redis.get_client()
        pipe = client.pipeline()
        key = self._key(ticket_id)
        pipe.get(key)
        pipe.delete(key)
        raw, _ = await pipe.execute()
        return json.decode(raw, type=HandshakeTicket) if raw else None
