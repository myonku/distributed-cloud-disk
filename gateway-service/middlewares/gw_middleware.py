import time
from typing import cast, Literal
from collections.abc import Callable
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse
from starlette.requests import Request

from services.gw_session_service import GatewaySessionService
from models.models import GatewaySession, BackendBinding
from services.registry_service import LocalRegistry
from config import GatewayRoutingConfig, ProjectConfig
from utils.selector_policy import pick_hash_affinity, random_weighted, pick_round_robin


class GatewayTrustRoutingMiddleware:
    """网关会话信任拦截 + 路由选择（模板实现）

    处理流程（HTTP 请求）：
    1. 解析 path / headers 获取会话 ID、设备指纹、节点会话 ID（占位）等。
    2. 若为握手路径且无网关会话：创建新 GatewaySession（匿名阶段），选择后端实例并生成初始绑定，透明转发握手。
    3. 非握手：加载网关会话；若路径不在匿名白名单且无会话 -> 401。
    4. 依据 REQUIRED_CRED_RULES 计算所需最低 cred；若会话信任缺失或 cred 不足 -> 403。
    5. 路由绑定：复用未过期的已存在 binding；如需重选则根据策略（hash/weighted/round_robin）与标签过滤（灰度）选择实例。
    6. 更新会话最近访问时间与 bindings（占位调用 session_svc）。
    7. 调用 _forward 透明转发（此处仅占位并返回模拟响应）。

    注意：真实实现中 _forward 应保持加密负载不被解析，仅处理必要明文字段。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_svc: GatewaySessionService,
        discovery: LocalRegistry,
        routing_cfg: GatewayRoutingConfig,
        route_strategy: Callable[[str, list[dict]], dict] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.session_svc = session_svc
        self.discovery = discovery
        self.cfg = routing_cfg
        self.clock = clock
        self.route_strategy = route_strategy  # 高级自定义策略占位
        self.session_header = "Gateway-Session-Id"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        path = request.url.path
        now = self.clock()

        # 会话标识 & 设备指纹（设备指纹可能用于风控 / 粘性key回退）
        gw_session_id = request.headers.get(self.session_header)
        device_fp = request.headers.get("Device-Fp")

        # 握手路径逻辑
        if self.cfg.is_handshake_path(path) and not gw_session_id:
            session = await self._create_anonymous_session(device_fp, now)
            binding = await self._pick_binding(
                session=session,
                service_name=self._infer_service_name(path),
                stickiness_key=self._stickiness_key(session),
                now=now,
            )
            if not binding:
                await self._json_error(
                    scope, receive, send, 503, "no instance for handshake"
                )
                return
            # 更新并转发（握手场景通常后端将建立节点会话并返回其 ID）
            await self._persist_binding(session, binding, now)
            resp = await self._forward(request, session, binding, handshake=True)
            await resp(scope, receive, send)
            return

        # 加载会话
        session = None
        if gw_session_id:
            session = await self.session_svc.get_session(gw_session_id)
        # 匿名访问校验
        if not session and not self.cfg.is_allow_anon(path):
            await self._json_error(
                scope, receive, send, 401, "unauthorized: session required"
            )
            return

        # 计算所需 cred
        required_cred = self.cfg.min_cred_for(path)
        if required_cred > 0:
            if not session or not session.trust or session.trust.cred < required_cred:
                await self._json_error(
                    scope, receive, send, 403, f"forbidden: cred<{required_cred}"
                )
                return

        # 选择或复用绑定
        binding = await self._ensure_binding(session, path, now, required_cred)
        if not binding:
            await self._json_error(
                scope, receive, send, 503, "no backend instance available"
            )
            return

        # 更新访问元数据（风控/QPS占位）
        if session:
            await self.session_svc.update_session(session, now)  # type: ignore[attr-defined]

        # 转发
        resp = await self._forward(request, session, binding)
        await resp(scope, receive, send)

    async def _create_anonymous_session(
        self, device_fp: str | None, now: float
    ) -> GatewaySession:
        return await self.session_svc.create_anonymous(device_fp, now)  # type: ignore[attr-defined]

    def _infer_service_name(self, path: str) -> str:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[1].startswith("v"):
            return parts[2]
        return parts[0] if parts else "user"

    def _stickiness_key(self, session: GatewaySession) -> str | None:
        if not self.cfg.STICKINESS_KEY:
            return None
        if session.trust and self.cfg.STICKINESS_KEY == "user_id":
            return session.trust.user_id
        return None

    async def _ensure_binding(
        self, session: GatewaySession | None, path: str, now: float, required_cred: int
    ) -> BackendBinding | None:
        service_name = self._infer_service_name(path)
        stickiness_key = self._stickiness_key(session) if session else None
        existing = self._find_existing_binding(session, service_name, now)
        if existing:
            return existing
        return await self._pick_binding(
            session=session,
            service_name=service_name,
            stickiness_key=stickiness_key,
            now=now,
            min_required_cred=required_cred,
        )

    def _find_existing_binding(
        self, session: GatewaySession | None, service_name: str, now: float
    ) -> BackendBinding | None:
        if not session:
            return None
        for b in session.bindings:
            if b.backend == service_name and b.expires_at > now:
                return b
        return None

    async def _pick_binding(
        self,
        session: GatewaySession | None,
        service_name: str,
        stickiness_key: str | None,
        now: float,
        min_required_cred: int | None = None,
    ) -> BackendBinding | None:
        instances = self.discovery.get_instances(service_name)
        if self.cfg.CANARY_TAGS:
            insts = [i for i in instances if set(self.cfg.CANARY_TAGS).issubset(i.tags)]
        else:
            insts = instances
        if not insts:
            return None
        strategy_used = self.cfg.DEFAULT_STRATEGY
        chosen = None
        if self.route_strategy:
            try:
                chosen_dict = self.route_strategy(service_name, [i.__dict__ for i in insts])
                endpoint = chosen_dict.get("endpoint")
                inst_id = chosen_dict.get("id")
                chosen = next((i for i in insts if i.id == inst_id or i.endpoint == endpoint), None)
                strategy_used = chosen_dict.get("strategy", strategy_used)
            except Exception:
                chosen = None
        if not chosen:
            if stickiness_key and strategy_used in {"hash_affinity", "weighted_random"}:
                chosen = pick_hash_affinity(insts, stickiness_key)
                strategy_used = "hash_affinity"
            if not chosen:
                if strategy_used == "round_robin":
                    chosen = pick_round_robin(insts, int(now))
                else:
                    chosen = random_weighted(insts)
                    strategy_used = "weighted_random"
        if not chosen:
            return None
        ttl = self.cfg.BINDING_TTL
        allowed = {"user", "metadata", "storage"}
        backend_literal = service_name if service_name in allowed else "user"
        binding = BackendBinding(
            backend=cast(Literal["user", "metadata", "storage"], backend_literal),
            selected_instance_id=chosen.id,
            selected_endpoint=chosen.endpoint,
            strategy_used=strategy_used,
            stickiness_key=stickiness_key,
            min_required_cred=min_required_cred,
            last_routed_at=now,
            expires_at=now + ttl,
            policy_trace=f"strategy={strategy_used};ttl={ttl}",
        )
        if session:
            await self._persist_binding(session, binding, now)
        return binding

    async def _persist_binding(
        self, session: GatewaySession, binding: BackendBinding, now: float
    ) -> None:
        await self.session_svc.upsert_binding(session.id, binding, now)  # type: ignore[attr-defined]

    async def _forward(
        self,
        request: Request,
        session: GatewaySession | None,
        binding: BackendBinding,
        handshake: bool = False,
    ) -> JSONResponse:
        return JSONResponse(
            {
                "handshake": handshake,
                "backend": binding.backend,
                "endpoint": binding.selected_endpoint,
                "strategy": binding.strategy_used,
                "session_id": session.id if session else None,
            }
        )

    async def _json_error(
        self, scope: Scope, receive: Receive, send: Send, status: int, msg: str
    ) -> None:
        resp = JSONResponse({"error": msg}, status_code=status)
        await resp(scope, receive, send)


def gateway_trust_routing_middleware_factory(
    app: ASGIApp, *, cfg: ProjectConfig | None = None
) -> ASGIApp:
    """延迟初始化的网关信任与路由中间件工厂。

    首次调用时：
    - 确认 Redis 已初始化（用于会话服务）
    - 读取配置获取 GatewayRoutingConfig
    若发现依赖不足则返回 503。
    若需要自定义 route_strategy，可在实例创建后通过属性注入。
    """

    class LazyGatewayTrustRoutingMiddleware:
        def __init__(self, app: ASGIApp, cfg: ProjectConfig | None = None):
            self.app = app
            self._middleware: GatewayTrustRoutingMiddleware | None = None
            self._session_svc: GatewaySessionService | None = None
            self._registry: LocalRegistry | None = None
            self._config: ProjectConfig | None = cfg

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if self._middleware is None:
                try:
                    from repositories.factory import redis  # 全局 RedisManager
                    if not redis.is_initialized:
                        resp = JSONResponse({"error": "Service Unavailable"}, status_code=503)
                        return await resp(scope, receive, send)
                    # 未传入配置，尝试读取配置
                    if not self._config:
                        from config import read_config
                        self._config = read_config("settings.toml")
                    # 未找到配置
                    if not self._config.routing_config:
                        resp = JSONResponse(
                            {"error": "config_missing"}, status_code=500
                        )
                        return await resp(scope, receive, send)
                    # 会话服务
                    self._session_svc = GatewaySessionService(redis)
                    # TODO: 发现注册服务引入，后续将在repositories.factory导入

                    self._middleware = GatewayTrustRoutingMiddleware(
                        self.app,
                        session_svc=self._session_svc,
                        discovery=self._registry, # type: ignore[arg-type]
                        routing_cfg=self._config.routing_config,
                    )
                except Exception as e:
                    resp = JSONResponse({"error": "init_failed", "detail": str(e)}, status_code=500)
                    return await resp(scope, receive, send)
            await self._middleware(scope, receive, send)

    return LazyGatewayTrustRoutingMiddleware(app, cfg)
