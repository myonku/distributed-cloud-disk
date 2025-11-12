from typing import Any
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


def encode_envelope(ev: EventEnvelope) -> bytes:
    return json.encode(ev)


def decode_envelope(data: bytes) -> EventEnvelope:
    return json.decode(data, type=EventEnvelope)