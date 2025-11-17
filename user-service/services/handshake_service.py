import os, base64, uuid
from typing import Any

from models.models import BackendSessionCache, TemporaryHandshake
from services.secretkey_service import ServerSecretKeyService
from services.session_service import BackendSessionSevice
from services.temp_hs_service import TemporaryHandshakeService
from utils.crypto_utils import (
    compute_verify_hmac,
    derive_session_keys_static,
    now_epoch,
)


VERIFY_GRACE = 30  # confirm 最长等待（秒）
SESSION_LIFETIME = 30 * 60  # 会话寿命（秒）


def _claims_defaults(ticket: Any) -> dict:
    return {"claims_hash": "init", "cred_level": 0, "roles": "", "tenant_id": None}


def _server_pub_to_b64(raw_pub_or_b64: bytes | str) -> str:
    if isinstance(raw_pub_or_b64, str):
        return raw_pub_or_b64
    return base64.b64encode(raw_pub_or_b64).decode()


class HandshakeService:
    """
    将握手逻辑封装为服务类：
    - init：验证票据，创建临时握手，返回 server 公钥、nonce、sessionId
    - confirm：校验 HMAC，落地 BackendSessionCache（无对称密钥），删除临时握手
    - derive_for_session：对业务中间件提供“随用随派生”能力
    """

    def __init__(
        self,
        temp_service: TemporaryHandshakeService,
        session_service: BackendSessionSevice,
    ):
        self.temp_service = temp_service
        self.session_service = session_service

    async def init(self, ticket_id: str, client_pub_eph_b64: str) -> dict:
        """初始握手"""

        # 服务器静态公钥/私钥（仅公钥用于响应）
        server_pub = ServerSecretKeyService.get_public_key()
        server_pub_b64 = _server_pub_to_b64(server_pub)

        # 生成 sessionId 与 serverNonce
        session_id = str(uuid.uuid4())
        server_nonce_b64 = base64.b64encode(os.urandom(16)).decode()

        now = now_epoch()
        temp = TemporaryHandshake(
            id=session_id,
            backend="user",
            client_pub_eph_b64=client_pub_eph_b64,
            server_pub_b64=server_pub_b64,
            server_nonce_b64=server_nonce_b64,
            created_at=now,
            expires_at=now + max(VERIFY_GRACE, 120),  # 至少 120s TTL
            verify_deadline_at=now + VERIFY_GRACE,
        )
        await self.temp_service.set(temp)

        return {
            "backendSessionId": session_id,
            "serverPublicKey": server_pub_b64,
            "serverNonce": server_nonce_b64,
            "aead": "AES-GCM",
            "kdf": "HKDF-SHA256",
            "verifyDeadline": VERIFY_GRACE,
        }

    async def confirm(self, backend_session_id: str, verify_hmac_hex: str) -> dict:
        """确认握手"""
        temp = await self.temp_service.get(backend_session_id)
        if not temp:
            return {"error": "handshake_not_found"}
        if temp.verify_deadline_at < now_epoch():
            await self.temp_service.delete(backend_session_id)
            return {"error": "verify_timeout"}

        # 以服务器静态私钥 + 客户端临时公钥 + sessionId 再派生
        server_priv = ServerSecretKeyService.get_private_key()
        c2s, s2c, fpr = derive_session_keys_static(
            client_pub_b64=temp.client_pub_eph_b64,
            server_priv_bytes=server_priv,
            session_id=temp.id,
            server_pub_b64=temp.server_pub_b64,
        )
        expected = compute_verify_hmac(c2s, s2c, temp.server_nonce_b64)

        # 常量时间比较
        import hmac

        if not hmac.compare_digest(verify_hmac_hex, expected):
            return {"error": "verify_failed"}

        now = now_epoch()
        sess = BackendSessionCache(
            id=temp.id,
            backend="user",
            client_pub_eph_b64=temp.client_pub_eph_b64,
            server_pub_b64=temp.server_pub_b64,
            shared_secret_fpr=fpr,
            verified=True,
            established_at=now,
            claims_refreshed_at=now,
            expires_at=now + SESSION_LIFETIME,
            **_claims_defaults(ticket=None),
        )
        await self.session_service.set_session(sess)
        await self.temp_service.delete(temp.id)
        return {
            "status": "ESTABLISHED",
            "fingerprint": fpr,
            "expiresIn": SESSION_LIFETIME,
        }

    async def derive_for_session(
        self, sess: BackendSessionCache
    ) -> tuple[bytes, bytes]:
        """
        供中间件调用：动态派生 c2s/s2c 密钥（不落地）
        """
        server_priv = ServerSecretKeyService.get_private_key()
        c2s, s2c, _ = derive_session_keys_static(
            client_pub_b64=sess.client_pub_eph_b64,
            server_priv_bytes=server_priv,
            session_id=sess.id,
            server_pub_b64=sess.server_pub_b64,
        )
        return c2s, s2c
