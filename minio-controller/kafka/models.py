import time
from typing import Any
import uuid
from msgspec import Struct, json


class EventEnvelope(Struct, frozen=True):
    """统一事件信封格式"""
    event_id: str
    type: str
    version: int
    ts: float
    aggregate_type: str
    aggregate_id: str
    source: str
    headers: dict[str, str]
    payload: dict[str, Any]


def new_envelope(
    *,
    type: str,
    aggregate_type: str,
    aggregate_id: str,
    source: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    version: int = 1,
    event_id: str | None = None,
    ts: float | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or str(uuid.uuid4()),
        type=type,
        version=version,
        ts=ts or time.time(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        source=source,
        headers=dict(headers or {}),
        payload=payload,
    )


def encode_envelope(ev: EventEnvelope) -> bytes:
    return json.encode(ev)


def decode_envelope(data: bytes) -> EventEnvelope:
    return json.decode(data, type=EventEnvelope)
