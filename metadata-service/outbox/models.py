from typing import Literal
from msgspec import Struct
import time, uuid

OutboxStatus = Literal["PENDING", "SENDING", "SENT", "FAILED", "DEAD"]


class OutboxRecord(Struct, frozen=False):
    """Outbox事件记录"""
    id: str
    dedup_id: str
    topic: str
    key: bytes | None
    partition: int | None
    headers: dict[str, str]
    payload: bytes
    event_type: str
    aggregate_type: str
    aggregate_id: str
    source: str
    version: int
    trace_id: str | None
    tenant_id: str | None
    status: OutboxStatus
    attempts: int
    next_attempt_at: float
    locked_by: str | None
    locked_at: float | None
    last_error: str | None
    created_at: float
    updated_at: float
    sent_at: float | None
    priority: int

    @staticmethod
    def new(
        *,
        topic: str,
        payload: bytes,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        source: str,
        version: int = 1,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
        dedup_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        priority: int = 0,
        first_delay_sec: float = 0.0,
    ) -> "OutboxRecord":
        now = time.time()
        rid = str(uuid.uuid4())
        return OutboxRecord(
            id=rid,
            dedup_id=dedup_id or rid,
            topic=topic,
            key=key,
            partition=None,
            headers=dict(headers or {}),
            payload=payload,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            source=source,
            version=version,
            trace_id=trace_id,
            tenant_id=tenant_id,
            status="PENDING",
            attempts=0,
            next_attempt_at=now + max(0.0, first_delay_sec),
            locked_by=None,
            locked_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
            sent_at=None,
            priority=priority,
        )
