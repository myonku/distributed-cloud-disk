from lihil import Route, Annotated, Param, status
import uuid, datetime as dt


handshake = Route("handshake")


@handshake.sub("init").post()
async def handshake_init(
    ticket_id: Annotated[str, Param("query")],
    client_pub_eph: Annotated[str, Param("body", decoder=lambda b: b.decode())],
) -> Annotated[dict, status.OK]:
    # 1. 取并销毁 ticket
    ticket = await session_store.pop_handshake_ticket(ticket_id)
    if not ticket:
        return {"error": "invalid or expired ticket"}
    # 2. 生成后端临时密钥
    server_pub, server_priv = CryptoSuite.generate_ephemeral_keypair()
    # (持久存储 priv 需要安全方式，这里简化；真实实现: 只存会话上下文)
    derived_key = CryptoSuite.derive_shared_key(client_pub_eph.encode(), server_priv)
    fpr = CryptoSuite.fingerprint(derived_key)
    backend_session_id = str(uuid.uuid4())
    bs = BackendSession(
        id=backend_session_id,
        user_id=ticket.user_id,
        backend_target=ticket.backend_target,
        shared_secret_fpr=fpr,
        client_pub_eph=client_pub_eph,
        server_pub_eph=(
            server_pub.decode() if isinstance(server_pub, bytes) else server_pub
        ),
        established_at=dt.datetime.utcnow(),
        expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=30),
    )
    await session_store.set_backend_session(bs)
    # 3. 返回服务器公钥与后续使用的 backend_session_id
    return {
        "backendSessionId": backend_session_id,
        "serverEphemeralPub": bs.server_pub_eph,
        "aead": "AES-GCM",
        "kdf": "HKDF-SHA256",
    }


@handshake.sub("confirm").post()
async def handshake_confirm(
    backend_session_id: Annotated[str, Param("header", alias="Backend-Session-Id")],
    confirm_payload: Annotated[str, Param("body", decoder=lambda b: b.decode())],
) -> Annotated[dict, status.OK]:
    # 可选：验证客户端对共享密钥的证明（例如: AEAD 加密 nonce=0 的 challenge）
    bs = await session_store.get_backend_session(backend_session_id)
    if not bs:
        return {"error": "session not found"}
    # 这里略过验证逻辑，仅返回已建立
    return {"status": "ESTABLISHED"}
