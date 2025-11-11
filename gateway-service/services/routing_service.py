from datetime import datetime
import time
from models.models import RoutingDecision
from repositories.redis_store import RedisManager
from msgspec import json


class RoutingDecisionService:
    """路由决策服务"""

    def __init__(self, redis_manager: RedisManager):
        self._rm = redis_manager
        self.prefix = "gw:routing_decision"

    def _key(self, tid: str) -> str:
        return f"{self.prefix}:{tid}"

    ...
