from msgspec import Struct
from typing import Literal


class GatewaySession(Struct):
    """网关中转会话"""
    id: str # UUID
    user_id: str | None
    stage: Literal[
        "pre_auth", "handshake_pending", "established"
    ]
    backend_hint: str | None
    created_at: float  # epoch 秒
    expires_at: float  # epoch 秒


class HandshakeTicket(Struct):
    """握手票据，仅在握手阶段使用"""
    id: str # UUID
    gateway_session_id: str # UUID
    backend_target: str
    user_id: str | None
    nonce: str  # 短期随机值
    created_at: float
    expires_at: float
