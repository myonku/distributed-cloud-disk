from kafka.models import EventEnvelope, encode_envelope
from .models import OutboxRecord
from .repo import OutboxRepository


class OutboxService:
    """提供“可靠事件写入”接口。"""

    def __init__(self, repo: OutboxRepository, reliable_topics: set[str]) -> None:
        self._repo = repo
        self._reliable_topics = reliable_topics

    async def save_reliable(
        self,
        *,
        envelope: EventEnvelope,
        topic: str,
        key: bytes | None,
        priority: int = 0,
        tx=None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
    ) -> OutboxRecord:
        """写入可靠事件"""
        if topic not in self._reliable_topics:
            raise ValueError(f"topic={topic} not configured as reliable/outbox-managed")
        encoded = encode_envelope(envelope)
        rec = OutboxRecord.new(
            topic=topic,
            payload=encoded,
            event_type=envelope.type,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            source=envelope.source,
            version=envelope.version,
            key=key,
            headers=envelope.headers,
            dedup_id=envelope.event_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            priority=priority,
        )
        await self._repo.insert(rec, tx=tx)
        return rec
