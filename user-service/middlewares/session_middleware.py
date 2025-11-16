from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Any

from msgspec import json

from services.session_service import BackendSessionSevice
from services.secretkey_service import ServerSecretKeyService
from utils.crypto_utils import derive_session_keys_static, aesgcm_decrypt, aesgcm_encrypt


class SessionMiddleware:
    """Session 合法性验证中间件"""

    def __init__(self, app: ASGIApp, session_service: BackendSessionSevice):
        self.app = app
        self.session_service = session_service
        self.session_header = "Session-Id"
        # 可选：需要对响应加密的路径前缀或精确匹配
        self.encrypt_response_paths: set[str] = set()
        # 基于路径/方法的最小 cred 校验规则
        # 精确匹配：path -> min_cred
        self.required_cred_exact: dict[str, int] = {}
        # 前缀匹配：[(prefix, min_cred)]，按长度优先匹配
        self.required_cred_prefix: list[tuple[str, int]] = []
        # 方法+精确匹配：((method, path) -> min_cred)
        self.required_cred_by_method: dict[tuple[str, str], int] = {}
        # 方法+前缀匹配：[(method, prefix, min_cred)]
        self.required_cred_prefix_by_method: list[tuple[str, str, int]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        if self._is_open_upath(request):
            await self.app(scope, receive, send)
            return

        session_id = request.headers.get(self.session_header)

        if not session_id:
            response = JSONResponse(
                status_code=401, content={"error": "Session ID is required"}
            )
            await response(scope, receive, send)
            return

        session = await self.session_service.get_session(session_id)
        if not session:
            response = JSONResponse(
                status_code=401, content={"error": "Session is Invalid!"}
            )
            await response(scope, receive, send)
            return
        if not session.verified:
            # TODO: 可选：发布验证失败事件、降低信任等级、revoke 等占位
            response = JSONResponse(
                status_code=403, content={"error": "session_not_verified"}
            )
            await response(scope, receive, send)
            return

        # 路径/方法基于 cred_level 的访问控制
        required_cred = self._resolve_required_cred(request.method, request.url.path)
        if required_cred is not None and session.cred_level < required_cred:
            response = JSONResponse(
                status_code=403,
                content={
                    "error": "insufficient_cred_level",
                    "required": required_cred,
                    "actual": session.cred_level,
                },
            )
            await response(scope, receive, send)
            return

        # 为本次请求派生会话密钥（不落地）
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

        # 读取原始请求体并按需解密
        try:
            raw_body = await request.body()
        except Exception:
            raw_body = b""

        content_enc = request.headers.get("Content-Enc") or request.headers.get("X-Content-Enc")
        decrypted_body = raw_body
        if (content_enc or "").lower() == "aes-gcm":
            try:
                obj = json.decode(raw_body) if raw_body else {}
                if not isinstance(obj, dict):
                    raise ValueError("encrypted payload must be a JSON object")
                nonce_b64 = obj.get("nonce") or obj.get("nonce_b64")
                ct_b64 = obj.get("ciphertext") or obj.get("ct") or obj.get("data")
                if not nonce_b64 or not ct_b64:
                    raise ValueError("missing nonce/ciphertext")
                # 可选将 AAD 绑定到路径/会话，增加绑定强度
                aad = f"{request.url.path}|{session.id}".encode()
                decrypted_body = aesgcm_decrypt(c2s, nonce_b64, ct_b64, aad=aad)
            except Exception as e:
                # 可选：发布验证失败事件/审计
                response = JSONResponse(
                    status_code=400, content={"error": "bad_encrypted_payload", "detail": str(e)}
                )
                await response(scope, receive, send)
                return

        # 将解密后的 body 通过自定义 receive 传给下游端点
        sent = {"done": False}

        async def receive_replay() -> dict[str, Any]:
            if not sent["done"]:
                sent["done"] = True
                return {"type": "http.request", "body": decrypted_body, "more_body": False}
            # 之后的读取返回空
            return {"type": "http.request", "body": b"", "more_body": False}

        # 是否需要对响应进行加密：按头或路径规则
        encrypt_resp = False
        resp_enc_hdr = request.headers.get("Response-Enc") or request.headers.get("X-Response-Enc")
        if (resp_enc_hdr or "").lower() == "aes-gcm":
            encrypt_resp = True
        else:
            if request.url.path in self.encrypt_response_paths:
                encrypt_resp = True

        async def send_wrapper(event):
            if not encrypt_resp:
                await send(event)
                return
            # 拦截并在最后一个 body 事件时整体加密
            if event["type"] == "http.response.start":
                # 调整响应头，标记加密与内容类型；去掉 content-length 以简化
                headers = []
                for k, v in (event.get("headers") or []):
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
                # 简化：假定框架一次性发送，如需分块可在此处缓存聚合
                if not more:
                    try:
                        aad = f"{request.url.path}|{session.id}".encode()
                        nonce_b64, ct_b64 = aesgcm_encrypt(s2c, body, aad=aad)
                        payload = {"nonce": nonce_b64, "ciphertext": ct_b64, "alg": "AES-GCM"}
                        enc_bytes = json.encode(payload)
                        await send({"type": "http.response.body", "body": enc_bytes, "more_body": False})
                        return
                    except Exception as e:
                        err = json.encode({"error": "response_encrypt_failed", "detail": str(e)})
                        await send({"type": "http.response.body", "body": err, "more_body": False})
                        return
            # 其余事件透传
            await send(event)

        # 将会话/密钥放入 scope 供端点使用（可选）
        scope["session_id"] = session_id
        scope["session"] = session
        scope["crypto_keys"] = {"c2s": c2s, "s2c": s2c}

        await self.app(scope, receive_replay, send_wrapper)

    def _is_open_upath(self, request: Request) -> bool:
        """检查是否是开放路由"""
        path = request.url.path
        return path.endswith(
            ("/health", "/handshake/init", "/handshake/confirm", "/favicon.ico")
        )

    def _resolve_required_cred(self, method: str, path: str) -> int | None:
        """计算某请求所需的最小 cred_level（若无规则则返回 None）"""
        # 方法+精确
        key = (method.upper(), path)
        if key in self.required_cred_by_method:
            return self.required_cred_by_method[key]
        # 方法+前缀（最长优先）
        if self.required_cred_prefix_by_method:
            best_len = -1
            best_val: int | None = None
            for m, prefix, val in self.required_cred_prefix_by_method:
                if m.upper() == method.upper() and path.startswith(prefix):
                    if len(prefix) > best_len:
                        best_len = len(prefix)
                        best_val = val
            if best_val is not None:
                return best_val
        # 全局精确
        if path in self.required_cred_exact:
            return self.required_cred_exact[path]
        # 全局前缀（最长优先）
        if self.required_cred_prefix:
            best_len = -1
            best_val = None
            for prefix, val in self.required_cred_prefix:
                if path.startswith(prefix) and len(prefix) > best_len:
                    best_len = len(prefix)
                    best_val = val
            if best_val is not None:
                return best_val
        return None

    def load_access_config(self, cfg: dict[str, Any] | None) -> None:
        """从对象导入访问控制/加密配置。

        适配推荐 TOML 的结构（示例 TOML）：

        [session_middleware]
        encrypt_response_paths = ["/secure/data", "/admin/secret"]

        [session_middleware.required_cred_exact]
        "/user/profile" = 1
        "/user/settings" = 1

        [[session_middleware.required_cred_prefix]]
        prefix = "/admin/"
        cred = 3

        [[session_middleware.required_cred_by_method]]
        method = "POST"
        path = "/user/transfer"
        cred = 2

        [[session_middleware.required_cred_prefix_by_method]]
        method = "DELETE"
        prefix = "/user/"
        cred = 2

        对应 Python dict 可以是：
        {
          "encrypt_response_paths": ["/secure/data"],
          "required_cred_exact": {"/user/profile": 1},
          "required_cred_prefix": [{"prefix": "/admin/", "cred": 3}],
          "required_cred_by_method": [{"method": "POST", "path": "/user/transfer", "cred": 2}],
          "required_cred_prefix_by_method": [{"method": "DELETE", "prefix": "/user/", "cred": 2}]
        }

        解析策略：
        - 不存在的键忽略。
        - 列表项中缺失必要字段将跳过并继续。
        - 重新加载时清空旧配置再写入。
        """
        if not cfg:
            return
        # 清空旧配置
        self.encrypt_response_paths.clear()
        self.required_cred_exact.clear()
        self.required_cred_prefix.clear()
        self.required_cred_by_method.clear()
        self.required_cred_prefix_by_method.clear()

        # 响应加密路径
        erp = cfg.get("encrypt_response_paths")
        if isinstance(erp, (list, tuple)):
            for p in erp:
                if isinstance(p, str):
                    self.encrypt_response_paths.add(p)

        # 精确 cred
        rce = cfg.get("required_cred_exact")
        if isinstance(rce, dict):
            for k, v in rce.items():
                if isinstance(k, str) and isinstance(v, int):
                    self.required_cred_exact[k] = v

        # 前缀 cred
        rcp = cfg.get("required_cred_prefix")
        if isinstance(rcp, (list, tuple)):
            for item in rcp:
                if not isinstance(item, dict):
                    continue
                prefix = item.get("prefix")
                cred = item.get("cred")
                if isinstance(prefix, str) and isinstance(cred, int):
                    self.required_cred_prefix.append((prefix, cred))
        # 保持最长优先匹配顺序（按长度倒序）
        self.required_cred_prefix.sort(key=lambda x: len(x[0]), reverse=True)

        # 方法+精确
        rcbm = cfg.get("required_cred_by_method")
        if isinstance(rcbm, (list, tuple)):
            for item in rcbm:
                if not isinstance(item, dict):
                    continue
                m = item.get("method")
                path = item.get("path")
                cred = item.get("cred")
                if isinstance(m, str) and isinstance(path, str) and isinstance(cred, int):
                    self.required_cred_by_method[(m.upper(), path)] = cred

        # 方法+前缀
        rcbmp = cfg.get("required_cred_prefix_by_method")
        if isinstance(rcbmp, (list, tuple)):
            for item in rcbmp:
                if not isinstance(item, dict):
                    continue
                m = item.get("method")
                prefix = item.get("prefix")
                cred = item.get("cred")
                if isinstance(m, str) and isinstance(prefix, str) and isinstance(cred, int):
                    self.required_cred_prefix_by_method.append((m.upper(), prefix, cred))
        # 排序保证最长前缀优先
        self.required_cred_prefix_by_method.sort(key=lambda x: len(x[1]), reverse=True)

        # 可扩展：日志或调试输出（此处简单略过）
        # print(f"SessionMiddleware config loaded: exact={len(self.required_cred_exact)} prefix={len(self.required_cred_prefix)}")


def session_middleware_factory(app: ASGIApp) -> ASGIApp:
    """
    Session 中间件工厂，使用延迟初始化提供中间件功能
    """

    # 创建一个包装器，在第一次调用时初始化真正的中间件
    class LazySessionMiddleware:

        def __init__(self, app: ASGIApp, session_mw_config: dict[str, Any] | None = None):
            self.app = app
            self._middleware: SessionMiddleware| None = None
            self._session_service: BackendSessionSevice | None = None
            self.session_mw_config = session_mw_config

        async def __call__(self, scope, receive, send):
            if self._middleware is None:
                # 延迟初始化
                from repositories.factory import redis

                if not redis.is_initialized:
                    # 如果 Redis 未初始化，拒绝所有请求
                    response = JSONResponse(
                        status_code=503, content={"error": "Service Unavailable"}
                    )
                    return await response(scope, receive, send)

                self._session_service = BackendSessionSevice(redis)
                self._middleware = SessionMiddleware(self.app, self._session_service)
                # 如果访问配置存在，直接加载
                if self.session_mw_config:
                    self._middleware.load_access_config(self.session_mw_config)

            await self._middleware(scope, receive, send)

    return LazySessionMiddleware(app)
