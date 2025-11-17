from typing import Any
from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.requests import Request
from starlette.responses import JSONResponse

from msgspec import json

from utils.crypto_utils import (
    aesgcm_decrypt,
    aesgcm_encrypt,
    derive_session_keys_static,
)
from services.secretkey_service import ServerSecretKeyService
from services.session_service import BackendSessionSevice


class CryptoMiddleware:
    """请求体按需解密 + 响应按需加密的中间件

    期望上游（如 GatewaySignatureMiddleware）已在 scope 注入：
    - session_id: str
    - session: SessionModel（需包含 id, client_pub_eph_b64, server_pub_b64）
    - crypto_keys: {"c2s": bytes, "s2c": bytes}

    若未注入，将尽量回退（按需）以保证兼容：
    - 当需要加解密但缺少 crypto_keys 时，尝试基于 scope["session"] 或基于 Session-Id 重新拉取会话与派生密钥。
    """

    def __init__(
        self, app: ASGIApp, session_service: BackendSessionSevice | None = None
    ):
        self.app = app
        self.session_service = session_service  # 仅用于回退场景
        # 配置：哪些路径要求加密/需要对响应加密
        self.encrypt_resp_exact: set[str] = set()
        self.encrypt_resp_prefixes: list[str] = []
        self.require_req_enc_exact: set[str] = set()
        self.require_req_enc_prefixes: list[str] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # 从 scope 读取注入的会话与密钥（优先使用）
        session = scope.get("session")
        session_id = scope.get("session_id") or request.headers.get("Session-Id")
        crypto_keys = (
            (scope.get("crypto_keys") or {})
            if isinstance(scope.get("crypto_keys"), dict)
            else {}
        )
        c2s = crypto_keys.get("c2s")
        s2c = crypto_keys.get("s2c")

        # 若配置不要求且请求头也不要求加密，且无密钥，直接透传
        must_decrypt = self._path_requires_request_encryption(request.url.path)
        want_encrypt_resp = self._path_requires_response_encryption(
            request.url.path
        ) or (
            (
                request.headers.get("Response-Enc")
                or request.headers.get("X-Response-Enc")
                or ""
            ).lower()
            == "aes-gcm"
        )
        need_crypto = (
            must_decrypt
            or want_encrypt_resp
            or (
                (
                    request.headers.get("Content-Enc")
                    or request.headers.get("X-Content-Enc")
                    or ""
                ).lower()
                == "aes-gcm"
            )
        )
        if need_crypto and (c2s is None or s2c is None):
            # 回退派生：优先使用 scope 中的 session；否则尝试通过 Session-Id 加载
            sess = session
            if sess is None and self.session_service and session_id:
                sess = await self.session_service.get_session(session_id)
            if sess is None:
                # 无法获取密钥，若请求或响应需要加密，则报错；否则放行
                if must_decrypt:
                    response = JSONResponse(
                        status_code=401, content={"error": "missing_crypto_keys"}
                    )
                    await response(scope, receive, send)
                    return
            else:
                try:
                    server_priv = ServerSecretKeyService.get_private_key()
                    c2s, s2c, _ = derive_session_keys_static(
                        client_pub_b64=sess.client_pub_eph_b64,
                        server_priv_bytes=server_priv,
                        session_id=sess.id,
                        server_pub_b64=sess.server_pub_b64,
                    )
                    # 更新 scope，供后续中间件/端点继续使用
                    scope["session"] = sess
                    scope["crypto_keys"] = {"c2s": c2s, "s2c": s2c}
                    if not session_id:
                        scope["session_id"] = getattr(sess, "id", None)
                except Exception as e:
                    if must_decrypt:
                        response = JSONResponse(
                            status_code=500,
                            content={"error": "key_derive_failed", "detail": str(e)},
                        )
                        await response(scope, receive, send)
                        return

        # 读取请求体并按需解密
        try:
            raw_body = await request.body()
        except Exception:
            raw_body = b""

        content_enc = request.headers.get("Content-Enc") or request.headers.get(
            "X-Content-Enc"
        )
        decrypted_body = raw_body
        is_encrypted = (content_enc or "").lower() == "aes-gcm"
        if (
            self._path_requires_request_encryption(request.url.path)
            and not is_encrypted
        ):
            response = JSONResponse(
                status_code=400, content={"error": "request_encryption_required"}
            )
            await response(scope, receive, send)
            return
        if is_encrypted:
            try:
                obj = json.decode(raw_body) if raw_body else {}
                if not isinstance(obj, dict):
                    raise ValueError("encrypted payload must be a JSON object")
                nonce_b64 = obj.get("nonce") or obj.get("nonce_b64")
                ct_b64 = obj.get("ciphertext") or obj.get("ct") or obj.get("data")
                if not nonce_b64 or not ct_b64:
                    raise ValueError("missing nonce/ciphertext")
                # AAD 绑定到路径/会话
                aad_id = getattr(session, "id", None) or session_id or ""
                aad = f"{request.url.path}|{aad_id}".encode()
                if not c2s:
                    raise ValueError("missing c2s key for decryption")
                decrypted_body = aesgcm_decrypt(c2s, nonce_b64, ct_b64, aad=aad)
            except Exception as e:
                response = JSONResponse(
                    status_code=400,
                    content={"error": "bad_encrypted_payload", "detail": str(e)},
                )
                await response(scope, receive, send)
                return

        sent = {"done": False}

        async def receive_replay() -> dict[str, Any]:
            if not sent["done"]:
                sent["done"] = True
                return {
                    "type": "http.request",
                    "body": decrypted_body,
                    "more_body": False,
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        # 是否需要对响应进行加密
        resp_enc_hdr = request.headers.get("Response-Enc") or request.headers.get(
            "X-Response-Enc"
        )
        encrypt_resp = (
            resp_enc_hdr or ""
        ).lower() == "aes-gcm" or self._path_requires_response_encryption(
            request.url.path
        )

        async def send_wrapper(event):
            if not encrypt_resp:
                await send(event)
                return
            if event["type"] == "http.response.start":
                headers = []
                for k, v in event.get("headers") or []:
                    lk = k.lower()
                    if lk in {b"content-length"}:
                        continue
                    if lk == b"content-type":
                        continue
                    headers.append((k, v))
                headers.append((b"content-type", b"application/json"))
                headers.append((b"content-enc", b"AES-GCM"))
                new_event = {**event, "headers": headers}
                await send(new_event)
                return
            if event["type"] == "http.response.body":
                body = event.get("body", b"") or b""
                more = bool(event.get("more_body"))
                if not more:
                    try:
                        aad_id = getattr(session, "id", None) or session_id or ""
                        aad = f"{request.url.path}|{aad_id}".encode()
                        if not s2c:
                            raise ValueError("missing s2c key for encryption")
                        nonce_b64, ct_b64 = aesgcm_encrypt(s2c, body, aad=aad)
                        payload = {
                            "nonce": nonce_b64,
                            "ciphertext": ct_b64,
                            "alg": "AES-GCM",
                        }
                        enc_bytes = json.encode(payload)
                        await send(
                            {
                                "type": "http.response.body",
                                "body": enc_bytes,
                                "more_body": False,
                            }
                        )
                        return
                    except Exception as e:
                        err = json.encode(
                            {"error": "response_encrypt_failed", "detail": str(e)}
                        )
                        await send(
                            {
                                "type": "http.response.body",
                                "body": err,
                                "more_body": False,
                            }
                        )
                        return
            await send(event)

        await self.app(scope, receive_replay, send_wrapper)

    # ------------------- 配置加载与路径匹配 -------------------
    def load_crypto_config(self, cfg: dict[str, Any] | None) -> None:  # type: ignore[override]
        if not cfg:
            return
        self.encrypt_resp_exact.clear()
        self.encrypt_resp_prefixes.clear()
        self.require_req_enc_exact.clear()
        self.require_req_enc_prefixes.clear()

        erp = cfg.get("encrypt_response_paths")
        if isinstance(erp, (list, tuple)):
            for p in erp:
                if isinstance(p, str):
                    self.encrypt_resp_exact.add(p)
        erpp = cfg.get("encrypt_response_prefixes")
        if isinstance(erpp, (list, tuple)):
            for p in erpp:
                if isinstance(p, str):
                    self.encrypt_resp_prefixes.append(p)
        self.encrypt_resp_prefixes.sort(key=lambda x: len(x), reverse=True)

        rreq = cfg.get("require_request_encryption_paths")
        if isinstance(rreq, (list, tuple)):
            for p in rreq:
                if isinstance(p, str):
                    self.require_req_enc_exact.add(p)
        rreqp = cfg.get("require_request_encryption_prefixes")
        if isinstance(rreqp, (list, tuple)):
            for p in rreqp:
                if isinstance(p, str):
                    self.require_req_enc_prefixes.append(p)
        self.require_req_enc_prefixes.sort(key=lambda x: len(x), reverse=True)

    def _path_requires_response_encryption(self, path: str) -> bool:
        if path in self.encrypt_resp_exact:
            return True
        return any(path.startswith(prefix) for prefix in self.encrypt_resp_prefixes)

    def _path_requires_request_encryption(self, path: str) -> bool:
        if path in self.require_req_enc_exact:
            return True
        return any(path.startswith(prefix) for prefix in self.require_req_enc_prefixes)


def crypto_middleware_factory(
    app: ASGIApp, config: dict[str, Any] | None = None
) -> ASGIApp:
    """加/解密中间件工厂。

    - 默认不依赖 Redis；若需要回退拉取会话与派生密钥，可在初始化前注入 session_service。
    - 这里提供简易工厂：仅创建中间件并加载配置。
    """

    class LazyCryptoMiddleware:
        def __init__(self, app: ASGIApp, cfg: dict[str, Any] | None = None):
            self.app = app
            self._middleware: CryptoMiddleware | None = None
            self._cfg = cfg

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if self._middleware is None:
                # 可选：如需回退从 Redis 获取会话，这里可注入 BackendSessionSevice(redis)
                self._middleware = CryptoMiddleware(self.app, session_service=None)
                if self._cfg:
                    self._middleware.load_crypto_config(self._cfg)
            await self._middleware(scope, receive, send)

    return LazyCryptoMiddleware(app, config)
