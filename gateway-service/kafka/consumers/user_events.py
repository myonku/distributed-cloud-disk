import asyncio
from collections.abc import Callable, Awaitable

from repositories.kafka_client import KafkaClient
from ..models import EventEnvelope, decode_envelope

TOPIC_USER_EVENTS = "dcd.user.events.v1"


class UserEventsConsumer:
    """
    消费用户域事件（USER_LOGGED_IN 等），用以刷新网关模块的会话状态。
    建议 handler 实现：
      - USER_LOGGED_IN: 将 payload 中的 session_id/user_id 等写入会话缓存或本地索引
      - USER_LOGGED_OUT / SESSION_REVOKED（未来扩展）: 失效对应会话
    """

    def __init__(
        self, kc: KafkaClient, group_id: str, bootstrap_servers: list[str]
    ) -> None:
        self.kc = kc
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, handler: Callable[[EventEnvelope], Awaitable[None]]) -> None:
        c = self.kc.create_consumer(
            topics=[TOPIC_USER_EVENTS],
            group_id=self.group_id,
            bootstrap_servers=self.bootstrap_servers,
            enable_auto_commit=False,
            auto_offset_reset="latest",
        )
        await c.start()

        async def _run():
            try:
                while not self._stop.is_set():
                    msg = await c.getone()
                    try:
                        val = msg.value
                        if not isinstance(val, (bytes, bytearray)):
                            await c.commit()
                            continue
                        env = decode_envelope(bytes(val))
                        if env.type in (
                            "USER_LOGGED_IN",
                            "USER_LOGGED_OUT",
                            "SESSION_REVOKED",
                        ):
                            await handler(env)
                        await c.commit()
                    except Exception as e:
                        # TODO: 重试/DLQ 路由（如 dcd.dlq.gateway.v1）
                        print(f"[UserEventsConsumer] handle error: {e}")
            finally:
                await c.stop()

        self._task = asyncio.create_task(_run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
