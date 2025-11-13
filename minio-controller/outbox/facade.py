import time
from kafka.models import encode_envelope, new_envelope
from outbox.service import OutboxService
from kafka.publisher import KafkaPublisher


# 非可靠（审计示例）
TOPIC_AUDIT_EVENTS = "dcd.audit.events.v1"


class DomainEventFacade:
    """
    同时提供：
      - 可靠（走 Outbox）
      - 非可靠（直接发）
    的统一入口，调用方无需关心实现细节。
    """

    def __init__(
        self,
        *,
        outbox: OutboxService,
        publisher: KafkaPublisher,
        source: str,
    ) -> None:
        self.outbox = outbox
        self.publisher = publisher
        self.source = source

    async def publish_request_audit(
        self,
        *,
        trace_id: str,
        route: str,
        method: str,
        user_id: str | None,
        status: int,
    ):
        """发布 请求审计 事件（非可靠，直接发）"""
        env = new_envelope(
            type="REQUEST_AUDIT",
            aggregate_type="http_request",
            aggregate_id=trace_id,
            source=self.source,
            payload={
                "trace_id": trace_id,
                "route": route,
                "method": method,
                "user_id": user_id,
                "status": status,
            },
        )
        await self.publisher.publish(
            topic=TOPIC_AUDIT_EVENTS,
            value=encode_envelope(env),
            key=trace_id.encode(),
        )
