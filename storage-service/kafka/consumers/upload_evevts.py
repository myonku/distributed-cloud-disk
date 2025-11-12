import asyncio
from collections.abc import Callable, Awaitable

from repositories.kafka_client import KafkaClient
from ..models import EventEnvelope, decode_envelope

TOPIC_UPLOAD_EVENTS = "dcd.upload.events.v1"


class UploadEventsConsumer:
    """消费上传域事件（如 UPLOAD_SESSION_CREATED），驱动存储侧初始化/预分配"""

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
            topics=[TOPIC_UPLOAD_EVENTS],
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
                        if not isinstance(msg.value, (bytes, bytearray)):
                            await c.commit()
                            continue
                        env = decode_envelope(bytes(msg.value))
                        if env.type in (
                            "UPLOAD_SESSION_CREATED",
                            "UPLOAD_SESSION_ABORTED",
                        ):
                            await handler(env)
                        await c.commit()
                    except Exception as e:
                        # TODO: retry/DLQ
                        print(f"[UploadEventsConsumer] handle error: {e}")
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
