from typing import Any
from msgspec import Struct, json


class EventEnvelope(Struct, frozen=True):
    """统一事件信封结构，用于所有事件的包装。"""

    event_id: str  # UUID
    type: str  # "UPLOAD_SESSION_CREATED" / "CHUNK_RECEIVED"
    version: int  # 1
    ts: float  # epoch seconds
    aggregate_type: str  # "upload_session" / "chunk" / "file"
    aggregate_id: str  # e.g. upload_session_id
    source: str  # "metadata-service"
    headers: dict[str, str]
    payload: dict[str, Any]  # 业务负载（简化：dict；复杂用 msgspec.Struct 嵌套）


def encode_envelope(ev: EventEnvelope) -> bytes:
    return json.encode(ev)


def decode_envelope(data: bytes) -> EventEnvelope:
    return json.decode(data, type=EventEnvelope)


class ChunkReceived(Struct, frozen=True):
    """文件块接收事件的负载结构。"""
    upload_session_id: str
    chunk_id: str
    index: int
    size: int
    node_id: str
    checksum: str | None = None


class UploadSessionCreated(Struct, frozen=True):
    """上传会话创建事件的负载结构。"""
    upload_session_id: str
    owner_id: str
    file_name: str
    size: int
    chunk_size: int
    placement_policy: str
