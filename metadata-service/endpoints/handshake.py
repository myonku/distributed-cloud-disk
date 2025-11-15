from lihil import Route, Annotated, Param, status
from models.dto_models import HandShakeConfirmDTO
from services.handshake_service import HandshakeService

handshake = Route("handshake", deps=[HandshakeService])


@handshake.sub("init").post
async def handshake_init(
    ticket_id: Annotated[str, Param("query")],
    client_pub_eph: Annotated[str, Param("body", decoder=lambda b: b.decode())],
    hs: HandshakeService,
) -> Annotated[dict, status.OK]:
    """
    请求体传 client_pub_eph（Base64 X25519 公钥）
    返回 backendSessionId、serverPublicKey（Base64）、serverNonce
    """
    return await hs.init(ticket_id=ticket_id, client_pub_eph_b64=client_pub_eph)


@handshake.sub("confirm").post
async def handshake_confirm(
    backend_session_id: Annotated[str, Param("header", alias="Backend-Session-Id")],
    confirm_data: Annotated[HandShakeConfirmDTO, Param("body")],
    hs: HandshakeService,
) -> Annotated[dict, status.OK]:
    """
    请求体 JSON: {"verifyHmac":"<hex>"} 由客户端使用 c2s/s2c + serverNonce 计算
    """
    verify_hmac = confirm_data.verify_hmac_b64
    if not verify_hmac:
        return {"error": "missing_verify_hmac"}
    return await hs.confirm(backend_session_id, verify_hmac)
