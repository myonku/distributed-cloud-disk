from msgspec import Struct
from typing import Literal


class GatewaySession(Struct):
    """网关中转会话"""

    id: str  # UUID
    user_id: str | None
    stage: Literal["pre_auth", "handshake_pending", "established"]
    backend_hint: str | None
    created_at: float  # epoch 秒
    expires_at: float  # epoch 秒


class HandshakeTicket(Struct, frozen=True):
    """网关分发的会话票据"""

    id: str
    gateway_session_id: str
    backend_target: str
    user_id: str | None
    nonce: str
    created_at: float
    expires_at: float
