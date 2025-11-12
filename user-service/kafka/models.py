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


class UserCreated(Struct, frozen=True):
    """记录用户创建事件的负载结构。"""
    user_id: str
    email: str
    display_name: str | None = None


class UserLoggedIn(Struct, frozen=True):
    """记录用户登录事件的负载结构。"""
    user_id: str
    session_id: str
    issued_at: float
    expires_at: float | None = None
    ip: str | None = None
    user_agent: str | None = None
    auth_method: str | None = None  # e.g. "password", "oauth", "webauthn"
    scopes: list[str] | None = None

class UserLoggedOut(Struct, frozen=True):
    """记录用户登出事件的负载结构。"""
    user_id: str
    session_id: str
    ts: float


def encode_envelope(ev: EventEnvelope) -> bytes:
    return json.encode(ev)


def decode_envelope(data: bytes) -> EventEnvelope:
    return json.decode(data, type=EventEnvelope)
