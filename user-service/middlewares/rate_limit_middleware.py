import time
from collections.abc import Callable
from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.requests import Request
from starlette.responses import JSONResponse

from repositories.redis_store import RedisManager
from services.session_service import BackendSessionSevice
from models.models import BackendSessionCache
from config import ProjectConfig, NodeRateLimitConfig


TOKEN_BUCKET_LUA = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local rate = tonumber(ARGV[2])
    local capacity = tonumber(ARGV[3])
    local cost = tonumber(ARGV[4])
    local ttl = tonumber(ARGV[5])

    local data = redis.call('HMGET', key, 'tokens', 'ts')
    local tokens = tonumber(data[1])
    local ts = tonumber(data[2])
    if tokens == nil then
    tokens = capacity
    ts = now
    end
    if ts == nil then ts = now end

    local delta = now - ts
    if delta < 0 then delta = 0 end
    local refill = delta * rate
    tokens = tokens + refill
    if tokens > capacity then tokens = capacity end

    local allowed = 0
    if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
    end

    redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
    redis.call('EXPIRE', key, ttl)
    return {allowed, tokens}
"""


class NodeRateLimitMiddleware:
    """节点侧分布式令牌桶限流中间件

    基于节点会话与用户/租户等信息做多维度限流：
    - 会话(session) -> 用户(user) -> 租户(tenant) -> 设备(device) / 匿名(anon)
    任一桶拒绝则整体拒绝（保守策略）。

    依赖上游 `GatewayAssertMiddleware` 注入：
    - scope["session_id"], scope["session"]: BackendSessionCache
    若缺失且配置允许，将使用请求头 `Session-Id` 回退从 Redis 加载一次。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_manager: RedisManager,
        session_service: BackendSessionSevice,
        rl_config: NodeRateLimitConfig,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self._rm = redis_manager
        self._sess = session_service
        self.cfg = rl_config
        self.clock = clock
        self.session_header = "Session-Id"
        self.device_fp_header = "Device-Fp"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path

        # 放行无需限流的开放路径（与会话相关握手/健康检查）
        if self._is_open_path(path):
            await self.app(scope, receive, send)
            return

        now = self.clock()

        # 会话、用户、租户、设备指纹信息
        session: BackendSessionCache | None = scope.get("session")
        session_id: str | None = scope.get("session_id") or request.headers.get(
            self.session_header
        )
        device_fp: str | None = request.headers.get(self.device_fp_header)

        # 如需回退从 Redis 获取一次会话
        if not session and self.cfg.FALLBACK_FETCH_SESSION and session_id:
            try:
                session = await self._sess.get_session(session_id)
            except Exception:
                session = None
            # 将回退获取到的会话注入 scope，便于后续中间件复用，避免二次读取
            if session is not None:
                scope["session"] = session
                scope.setdefault("session_id", session_id)

        # 构造桶维度（有序）：session -> user -> tenant -> device/anon
        buckets: list[tuple[str, str]] = []
        if session_id:
            buckets.append(("session", session_id))
        if session and session.user_id and self.cfg.ENABLE_USER_BUCKET:
            buckets.append(("user", session.user_id))
        if session and session.tenant_id and self.cfg.ENABLE_TENANT_BUCKET:
            buckets.append(("tenant", session.tenant_id))
        if device_fp and self.cfg.ENABLE_DEVICE_BUCKET:
            buckets.append(("device", device_fp))
        if not buckets:
            client_ip = request.client.host if request.client else "unknown"
            buckets.append(("anon", client_ip))

        # 执行限流：任一桶拒绝则整体拒绝
        for scope_name, identifier in buckets:
            allowed = await self._consume(scope_name, identifier, now)
            if not allowed:
                await self._reject(scope, receive, send, scope_name)
                return

        await self.app(scope, receive, send)

    async def _consume(self, scope_name: str, identifier: str, now: float) -> bool:
        """执行单桶令牌消费。"""
        client = self._rm.get_client()
        rate, capacity = self.cfg.bucket_params(scope_name)
        cost = self.cfg.COST_PER_REQUEST
        ttl = int((capacity / max(rate, 0.0001)) * 3)
        ttl = max(ttl, 5)
        prefix = self.cfg.KEY_PREFIX
        key = f"{prefix}:{scope_name}:{identifier}"
        try:
            res = await client.execute_command(
                "EVAL",
                TOKEN_BUCKET_LUA,
                1,
                key,
                now,
                rate,
                capacity,
                cost,
                ttl,
            )
            if not res or not isinstance(res, (list, tuple)) or len(res) < 2:
                # 异常返回时放行，避免误伤
                return True
            allowed = int(res[0])
            return allowed == 1 or not self.cfg.BLOCK_ON_EMPTY
        except Exception:
            # Redis 异常走 fail-open 策略（可按需改为 fail-closed）
            return True

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, scope_name: str
    ) -> None:
        resp = JSONResponse(
            {"error": "rate_limited", "scope": scope_name}, status_code=429
        )
        await resp(scope, receive, send)

    @staticmethod
    def _is_open_path(path: str) -> bool:
        return path.endswith(
            ("/health", "/handshake/init", "/handshake/confirm", "/favicon.ico")
        )


def node_rate_limit_middleware_factory(
    app: ASGIApp,
    *,
    cfg: ProjectConfig | None = None,
) -> ASGIApp:
    """延迟初始化的节点限流中间件工厂。

    - 依赖 Redis 初始化完成；
    - 依赖 `BackendSessionSevice` 获取会话信息（回退使用）。
    """

    class LazyNodeRateLimitMiddleware:
        def __init__(self, app: ASGIApp):
            self.app = app
            self._middleware: NodeRateLimitMiddleware | None = None
            self.rl_config = cfg

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if self._middleware is None:
                from repositories.factory import redis
                if not redis.is_initialized:
                    resp = JSONResponse(
                        {"error": "Service Unavailable"}, status_code=503
                    )
                    return await resp(scope, receive, send)
                # 未传入配置时从文件加载默认配置
                if self.rl_config is None:
                    from config import read_config
                    self.rl_config = read_config("settings.toml")
                # 未找到配置
                if not self.rl_config.rate_limit:
                    resp = JSONResponse(
                        {"error": "config_missing"}, status_code=500
                    )
                    return await resp(scope, receive, send)
                sess_svc = BackendSessionSevice(redis)
                self._middleware = NodeRateLimitMiddleware(
                    self.app,
                    redis_manager=redis,
                    session_service=sess_svc,
                    rl_config=self.rl_config.rate_limit,
                )
            await self._middleware(scope, receive, send)

    return LazyNodeRateLimitMiddleware(app)
