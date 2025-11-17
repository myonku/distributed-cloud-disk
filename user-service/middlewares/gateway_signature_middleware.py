from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.session_service import BackendSessionSevice
from services.secretkey_service import ServerSecretKeyService
from utils.crypto_utils import derive_session_keys_static


class GatewayAssertMiddleware:
    """网关签名校验 + 会话加载 + 密钥派生

    作用：
    - 校验 `Session-Id` 头并加载会话
    - 校验网关签名（占位：检查签名存在与基本长度）
    - 依据会话信息与服务端私钥派生 c2s/s2c 会话密钥
    - 将 `session_id`、`session`、`crypto_keys` 注入到 scope 供下游中间件/端点使用
    """

    def __init__(self, app: ASGIApp, session_service: BackendSessionSevice):
        self.app = app
        self.session_service = session_service
        self.session_header = "Session-Id"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # 放行无需会话/签名的开放路径（握手/健康检查）
        if self._is_open_path(request.url.path):
            await self.app(scope, receive, send)
            return

        session_id = request.headers.get(self.session_header)
        if not session_id:
            response = JSONResponse(status_code=401, content={"error": "Session ID is required"})
            await response(scope, receive, send)
            return

        session = await self.session_service.get_session(session_id)
        if not session:
            response = JSONResponse(status_code=401, content={"error": "Session is Invalid!"})
            await response(scope, receive, send)
            return

        # 网关签名占位校验
        sig = request.headers.get("Gateway-Signature") or request.headers.get("X-Gateway-Signature")
        if not sig or len(sig) < 16:
            response = JSONResponse(status_code=401, content={"error": "invalid_gateway_signature"})
            await response(scope, receive, send)
            return

        # 派生一次会话密钥并注入 scope
        try:
            server_priv = ServerSecretKeyService.get_private_key()
            c2s, s2c, _ = derive_session_keys_static(
                client_pub_b64=session.client_pub_eph_b64,
                server_priv_bytes=server_priv,
                session_id=session.id,
                server_pub_b64=session.server_pub_b64,
            )
        except Exception as e:
            response = JSONResponse(status_code=500, content={"error": "key_derive_failed", "detail": str(e)})
            await response(scope, receive, send)
            return

        scope["session_id"] = session_id
        scope["session"] = session
        scope["crypto_keys"] = {"c2s": c2s, "s2c": s2c}

        await self.app(scope, receive, send)

    @staticmethod
    def _is_open_path(path: str) -> bool:
        return path.endswith(("/health", "/handshake/init", "/handshake/confirm", "/favicon.ico"))


def gateway_signature_middleware_factory(app: ASGIApp) -> ASGIApp:
    """延迟初始化的网关签名中间件工厂（确保 Redis 已初始化）。"""

    class LazyGatewaySignatureMiddleware:
        def __init__(self, app: ASGIApp):
            self.app = app
            self._middleware: GatewayAssertMiddleware | None = None
            self._session_service: BackendSessionSevice | None = None

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if self._middleware is None:
                from repositories.factory import redis
                if not redis.is_initialized:
                    response = JSONResponse(status_code=503, content={"error": "Service Unavailable"})
                    return await response(scope, receive, send)

                self._session_service = BackendSessionSevice(redis)
                self._middleware = GatewayAssertMiddleware(self.app, self._session_service)

            await self._middleware(scope, receive, send)

    return LazyGatewaySignatureMiddleware(app)
