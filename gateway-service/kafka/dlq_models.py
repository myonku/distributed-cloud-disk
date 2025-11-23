import time
import uuid
from msgspec import Struct, json
from .models import EventEnvelope


class DeadLetterPayload(Struct, frozen=True):
    """死信事件负载（用于统一处理与检索）

    字段说明:
    - original_event_id: 原事件的 ID（便于对账与去重）
    - original_type: 原事件类型（如 CHUNK_RECEIVED）
    - original_aggregate_type / original_aggregate_id: 聚合信息
    - handler: 发生失败的处理器/消费者标识（group+handler_key）
    - attempt: 第几次处理失败（从 1 开始）
    - reason: 简要失败原因（分类码或文本）
    - error: 详细错误描述（栈或截断的消息）
    - partition / offset: Kafka 位置（用于定位与人工重放）
    - tenant_id / trace_id: 透传上下文
    - first_failed_ts / last_failed_ts: 首次与最近失败时间（秒级）
    - max_attempts: 达到的最大尝试次数（可用于停用后续自动重试）
    - retryable: 是否可继续自动重试（策略判定）
    - original_envelope_json: 原事件 envelope 的 JSON（存档）
    """

    original_event_id: str
    original_type: str
    original_aggregate_type: str
    original_aggregate_id: str
    handler: str
    attempt: int
    reason: str
    error: str | None
    partition: int | None
    offset: int | None
    tenant_id: str | None
    trace_id: str | None
    first_failed_ts: float
    last_failed_ts: float
    max_attempts: int | None
    retryable: bool
    original_envelope_json: str


class DeadLetterEnvelope(Struct, frozen=True):
    """死信事件统一封装（区别于业务事件 envelope）

    这里不复用 EventEnvelope 以便与正常事件区分；也可选择直接用 EventEnvelope.type = DEAD_LETTER。
    """

    dlq_event_id: str
    version: int
    ts: float
    source: str  # 产生死信的服务标识（通常为消费者所在服务）
    headers: dict[str, str]
    payload: DeadLetterPayload


def new_dead_letter_envelope(
    *,
    source: str,
    payload: DeadLetterPayload,
    headers: dict[str, str] | None = None,
    version: int = 1,
    dlq_event_id: str | None = None,
    ts: float | None = None
) -> DeadLetterEnvelope:
    return DeadLetterEnvelope(
        dlq_event_id=dlq_event_id or str(uuid.uuid4()),
        version=version,
        ts=ts or time.time(),
        source=source,
        headers=dict(headers or {}),
        payload=payload,
    )


def encode_dead_letter(ev: DeadLetterEnvelope) -> bytes:
    return json.encode(ev)


def decode_dead_letter(data: bytes) -> DeadLetterEnvelope:
    return json.decode(data, type=DeadLetterEnvelope)


def build_dead_letter_payload(
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
    first_failed_ts: float | None,
    last_failed_ts: float | None,
    max_attempts: int | None,
    retryable: bool
) -> DeadLetterPayload:
    return DeadLetterPayload(
        original_event_id=original.event_id,
        original_type=original.type,
        original_aggregate_type=original.aggregate_type,
        original_aggregate_id=original.aggregate_id,
        handler=handler,
        attempt=attempt,
        reason=reason,
        error=error,
        partition=partition,
        offset=offset,
        tenant_id=tenant_id,
        trace_id=trace_id,
        first_failed_ts=first_failed_ts or time.time(),
        last_failed_ts=last_failed_ts or time.time(),
        max_attempts=max_attempts,
        retryable=retryable,
        original_envelope_json=json.decode(
            json.encode(original)
        ).__repr__(),  # 简单序列化，可替换为更紧凑方案
    )
