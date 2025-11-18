import time
from collections.abc import Callable
from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.requests import Request
from starlette.responses import JSONResponse
from repositories.redis_store import RedisManager
from services.gw_session_service import GatewaySessionService
from config import ProjectConfig, RateLimitConfig, GatewayRoutingConfig


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


class DistributedRateLimitMiddleware:
    """会话/用户级分布式令牌桶限流中间件 (模板实现)

    算法：令牌桶 (Token Bucket)
    - 每个维度一个 Redis Hash: rl:{scope}:{id}
      字段: tokens(剩余令牌), ts(上次补充时间秒)
    - 请求到来时：补充 = (now - ts) * rate; 新 tokens = min(capacity, tokens + 补充)
    - 若 tokens >= cost 则扣减并允许，否则拒绝。
    - TTL 设为 (capacity / rate * 3) 以便闲时自动回收键。

    Lua 保证原子性，减少网络往返与竞态。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_manager: RedisManager,
        session_svc: GatewaySessionService,
        rl_config: RateLimitConfig,
        routing_config: GatewayRoutingConfig,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self._rm = redis_manager
        self._sess = session_svc
        self.cfg = rl_config
        self.routing_cfg = routing_config
        self.clock = clock

        self.session_header = "Gateway-Session-Id"
        self.device_fp_header = "Device-Fp"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        path = request.url.path
        now = self.clock()

        # 握手路径可单独使用 anon/session 桶；这里统一走逻辑
        gw_session_id = request.headers.get(self.session_header)
        device_fp = request.headers.get(self.device_fp_header)
        # 如果是握手且没有会话 -> 走 anon + device 桶
        is_handshake = self.routing_cfg.is_handshake_path(path)

        # 维度检查顺序：会话 -> 用户 -> 设备/匿名
        buckets: list[tuple[str, str]] = []  # (scope, id)
        if gw_session_id:
            buckets.append(("session", gw_session_id))
        if gw_session_id:  # 已有会话，尝试用户 ID（需从会话中解析）
            session = await self._sess.get_session(gw_session_id)
            if session and session.trust and self.cfg.ENABLE_USER_BUCKET:
                buckets.append(("user", session.trust.user_id))
        if device_fp and self.cfg.ENABLE_DEVICE_BUCKET:
            buckets.append(("device", device_fp))
        if not buckets:  # 完全匿名
            if is_handshake and device_fp:
                buckets.append(("anon_device", device_fp))
            else:
                buckets.append(
                    ("anon", request.client.host if request.client else "unknown")
                )

        # 执行限流，若任一桶拒绝则整体拒绝（最保守策略）
        for scope_name, identifier in buckets:
            allowed = await self._consume(scope_name, identifier, now)
            if not allowed:
                await self._reject(scope, receive, send, scope_name)
                return

        # 通过，继续后续中间件
        await self.app(scope, receive, send)

    async def _consume(self, scope_name: str, identifier: str, now: float) -> bool:
        """尝试从指定桶消费令牌，成功返回 True，失败或异常返回 False"""
        client = self._rm.get_client()
        rate, capacity = self.cfg.bucket_params(scope_name)
        cost = self.cfg.COST_PER_REQUEST
        ttl = int((capacity / max(rate, 0.0001)) * 3)
        ttl = max(ttl, 5)
        key = f"rl:{scope_name}:{identifier}"
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
                return True  # 回退: 异常时放行
            allowed, _ = int(res[0]), res[1]
            return allowed == 1 or not self.cfg.BLOCK_ON_EMPTY
        except Exception:
            # Redis 异常：降级策略（fail-open）或 fail-closed；这里选择 fail-open
            return True

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, scope_name: str
    ) -> None:
        resp = JSONResponse(
            {"error": "rate_limited", "scope": scope_name}, status_code=429
        )
        await resp(scope, receive, send)


def rate_limit_middleware_factory(
    app: ASGIApp, *, cfg: ProjectConfig | None = None
) -> ASGIApp:
    """延迟初始化的分布式限流中间件工厂。

    首次收到请求时：
    - 检查全局 redis (repositories.factory.redis) 是否已初始化
    - 读取配置（settings.toml）获得 RateLimitConfig 与 GatewayRoutingConfig
    - 初始化 GatewaySessionService 与 DistributedRateLimitMiddleware
    如果依赖未就绪返回 503。
    可在后续根据需要替换配置（中间件实例暴露 cfg 属性）。
    """

    class LazyRateLimitMiddleware:
        def __init__(self, app: ASGIApp, cfg: ProjectConfig | None = None):
            self.app = app
            self._middleware: DistributedRateLimitMiddleware | None = None
            self._session_service: GatewaySessionService | None = None
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

                    self._routing_cfg = self._config.routing_config
                    self._session_service = GatewaySessionService(redis)
                    # 未找到配置
                    if not self._config.rate_limit or not self._config.routing_config:
                        resp = JSONResponse(
                            {"error": "config_missing"}, status_code=500
                        )
                        return await resp(scope, receive, send)
                    self._middleware = DistributedRateLimitMiddleware(
                        self.app,
                        redis_manager=redis,
                        session_svc=self._session_service,
                        rl_config=self._config.rate_limit,
                        routing_config=self._config.routing_config,
                    )
                except Exception as e:
                    resp = JSONResponse({"error": "init_failed", "detail": str(e)}, status_code=500)
                    return await resp(scope, receive, send)
            await self._middleware(scope, receive, send)

    return LazyRateLimitMiddleware(app, cfg)
