import asyncio
from collections.abc import Awaitable, Callable
import time
from typing import Any, Literal

from config import CircuitBreakerConfig


class CircuitOpenError(RuntimeError):
    """熔断已打开时抛出的异常。"""


class CircuitBreaker:
    """简单的进程内熔断器实现（单实例内线程安全需求较低）。"""

    def __init__(self, name: str, cfg: CircuitBreakerConfig | None = None):
        self.name = name
        self.cfg = cfg or CircuitBreakerConfig()
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._failure_count: int = 0
        self._last_failure_ts: float = 0.0
        self._half_open_in_flight: int = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def _before_call(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._state == "open":
                # 冷却时间未到，直接拒绝
                if now - self._last_failure_ts < self.cfg.recovery_timeout:
                    raise CircuitOpenError(f"circuit '{self.name}' is open")
                # 冷却时间已到，进入 half-open
                self._state = "half_open"
                self._half_open_in_flight = 0

            if self._state == "half_open":
                if self._half_open_in_flight >= self.cfg.half_open_max_calls:
                    raise CircuitOpenError(
                        f"circuit '{self.name}' is half-open and busy"
                    )
                self._half_open_in_flight += 1

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._half_open_in_flight = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_ts = time.monotonic()
            if self._failure_count >= self.cfg.failure_threshold:
                self._state = "open"
                self._half_open_in_flight = 0

    async def call(self, func: Callable[[], Awaitable[Any]]) -> Any:
        """包装异步调用：根据当前熔断状态决定是否放行或短路。"""

        await self._before_call()
        try:
            result = await func()
        except Exception:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result
        finally:
            # HALF_OPEN 探测调用结束，释放占用
            async with self._lock:
                if self._state == "half_open" and self._half_open_in_flight > 0:
                    self._half_open_in_flight -= 1
