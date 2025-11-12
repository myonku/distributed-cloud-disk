import time, uuid
from collections.abc import Mapping
from aiokafka.structs import RecordMetadata
from msgspec import json

from repositories.kafka_client import KafkaClient
from ..models import (
    EventEnvelope,
    UserCreated,
    UserLoggedIn,
    UserLoggedOut,
    encode_envelope,
)

TOPIC_USER_EVENTS = "dcd.user.events.v1"


class UserEventProducer:
    """用户域事件生产者"""

    def __init__(self, kc: KafkaClient) -> None:
        self.kc = kc

    async def publish_user_created(
        self,
        user_id: str,
        email: str,
        display_name: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        """发布用户创建事件"""
        payload = UserCreated(user_id=user_id, email=email, display_name=display_name)
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="USER_CREATED",
            version=1,
            ts=time.time(),
            aggregate_type="user",
            aggregate_id=user_id,
            source="user-service",
            headers=dict(headers or {}),
            payload=json.decode(json.encode(payload)),
        )
        prod = self.kc.get_producer()
        md = await prod.send_and_wait(
            TOPIC_USER_EVENTS,
            value=encode_envelope(env),
            key=user_id.encode(),
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
        return md

    async def publish_user_logged_in(
        self,
        user_id: str,
        session_id: str,
        issued_at: float | None = None,
        expires_at: float | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        auth_method: str | None = None,
        scopes: list[str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        """发布用户登录成功事件，用于网关/控制面刷新会话状态"""
        now = time.time()
        payload = UserLoggedIn(
            user_id=user_id,
            session_id=session_id,
            issued_at=issued_at or now,
            expires_at=expires_at,
            ip=ip,
            user_agent=user_agent,
            auth_method=auth_method,
            scopes=scopes,
        )
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="USER_LOGGED_IN",
            version=1,
            ts=now,
            aggregate_type="user_session",
            aggregate_id=session_id,
            source="user-service",
            headers=dict(headers or {}),
            payload=json.decode(json.encode(payload)),
        )
        # 以 session_id 作为 key 保证同一会话内消息顺序；也可改为 user_id 聚合
        key = session_id.encode()
        prod = self.kc.get_producer()
        md = await prod.send_and_wait(
            TOPIC_USER_EVENTS,
            value=encode_envelope(env),
            key=key,
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
        return md

    async def publish_user_logout(
        self,
        user_id: str,
        session_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        """发布用户登出事件"""
        now = time.time()
        payload = UserLoggedOut(
            user_id=user_id,
            session_id=session_id,
            ts=now,
        )
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="USER_LOGGED_OUT",
            version=1,
            ts=now,
            aggregate_type="user_session",
            aggregate_id=session_id,
            source="user-service",
            headers=dict(headers or {}),
            payload=json.decode(json.encode(payload)),
        )
        key = session_id.encode()
        prod = self.kc.get_producer()
        md = await prod.send_and_wait(
            TOPIC_USER_EVENTS,
            value=encode_envelope(env),
            key=key,
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
        return md
