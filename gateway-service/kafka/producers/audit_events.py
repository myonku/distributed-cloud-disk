import time, uuid
from collections.abc import Mapping
from aiokafka.structs import RecordMetadata

from repositories.kafka_client import KafkaClient
from ..models import (
    EventEnvelope,
    encode_envelope,
)

TOPIC_AUDIT_EVENTS = "dcd.audit.events.v1"


class AuditEventProducer:
    """API 网关审计事件生产者"""

    def __init__(self, kc: KafkaClient) -> None:
        self.kc = kc

    async def publish_request_audit(
        self,
        trace_id: str,
        route: str,
        method: str,
        user_id: str | None,
        status: int,
        headers: Mapping[str, str] | None = None,
    ) -> RecordMetadata:
        """发布请求审计事件到 Kafka"""
        env = EventEnvelope(
            event_id=str(uuid.uuid4()),
            type="REQUEST_AUDIT",
            version=1,
            ts=time.time(),
            aggregate_type="http_request",
            aggregate_id=trace_id,
            source="gateway-service",
            headers=dict(headers or {}),
            payload={
                "trace_id": trace_id,
                "route": route,
                "method": method,
                "user_id": user_id,
                "status": status,
            },
        )
        prod = self.kc.get_producer()
        return await prod.send_and_wait(
            TOPIC_AUDIT_EVENTS,
            value=encode_envelope(env),
            key=trace_id.encode(),
            headers=[(k, v.encode()) for k, v in env.headers.items()],
        )
