from aiokafka.structs import RecordMetadata
from kafka.kafka_client import KafkaClient
from .models import EventEnvelope
from .dlq_models import (
    build_dead_letter_payload,
    new_dead_letter_envelope,
    encode_dead_letter,
)

DLQ_TOPIC_DEFAULT = "dcd.deadletter.events.v1"

class DeadLetterPublisher:
    """死信事件发布器（直接发送或可扩展走 Outbox）

    使用场景：在消费者处理失败且超过重试阈值/判定不可重试时，发布死信。
    建议在业务消费逻辑中：
      - 保留原事件 envelope
      - 累计 attempt 次数
      - 根据策略(retryable / max_attempts)决定何时进入 DLQ
    后续由专门的 DLQ 处理服务订阅进行人工干预/补偿/重放。
    """

    def __init__(self, kc: KafkaClient, topic: str = DLQ_TOPIC_DEFAULT, source: str = "storage-service") -> None:
        self._kc = kc
        self._topic = topic
        self._source = source

    async def publish_dead_letter(
        self,
        *,
        original: EventEnvelope,
        handler: str,
        attempt: int,
        reason: str,
        error: str | None,
        partition: int | None,
        offset: int | None,
        tenant_id: str | None,
        trace_id: str | None,
        max_attempts: int | None,
        retryable: bool,
        headers: dict[str, str] | None = None,
    ) -> RecordMetadata:
        payload = build_dead_letter_payload(
            original=original,
            handler=handler,
            attempt=attempt,
            reason=reason,
            error=error,
            partition=partition,
            offset=offset,
            tenant_id=tenant_id,
            trace_id=trace_id,
            first_failed_ts=None,  # 首次失败时间若需要跨尝试持久化，可外部传入
            last_failed_ts=None,
            max_attempts=max_attempts,
            retryable=retryable,
        )
        envelope = new_dead_letter_envelope(source=self._source, payload=payload, headers=headers)
        prod = self._kc.get_producer()
        md = await prod.send_and_wait(
            self._topic,
            key=payload.original_event_id.encode(),
            value=encode_dead_letter(envelope),
            headers=[(k, v.encode()) for k, v in (headers or {}).items()],
        )
        return md
