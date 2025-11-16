from msgspec import Struct
from typing import Any
import time


class InboxProcessed(Struct, frozen=False):
    """消费者侧幂等占位记录（已处理事件标记）。

    主键建议使用 (handler, event_id) 复合键，达到“同一事件对同一处理器只处理一次”。
    handler 可取 "<service>:<topic>|<event_type>" 或更细粒度的消费者名。
    """

    handler: str
    event_id: str
    aggregate_type: str | None = None
    aggregate_id: str | None = None
    tenant_id: str | None = None
    processed_at: float = 0.0
    extra: dict[str, Any] | None = None

    @staticmethod
    def new(
        *,
        handler: str,
        event_id: str,
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        tenant_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> "InboxProcessed":
        return InboxProcessed(
            handler=handler,
            event_id=event_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            tenant_id=tenant_id,
            processed_at=time.time(),
            extra=extra or {},
        )
