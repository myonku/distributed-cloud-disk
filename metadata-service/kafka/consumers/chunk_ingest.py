import asyncio
from collections.abc import Callable, Awaitable
from kafka.kafka_client import KafkaClient
from ..models import EventEnvelope, decode_envelope

TOPIC_CHUNK_EVENTS = "dcd.chunk.events.v1"


class ChunkIngestConsumer:
    """
    消费存储节点的分片事件（CHUNK_RECEIVED 等），推进上传会话状态
    - 幂等/重试: 占位（建议引入去重表/Redis set）
    - DLQ: 占位（失败时转发到 dcd.dlq.metadata.v1）
    """

    def __init__(
        self, kc: KafkaClient, group_id: str, bootstrap_servers: list[str]
    ) -> None:
        self.kc = kc
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, handler: Callable[[EventEnvelope], Awaitable[None]]):
        c = self.kc.create_consumer(
            topics=[TOPIC_CHUNK_EVENTS],
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
                        if val is None:
                            # missing payload; skip and commit offset
                            print("[ChunkIngest] empty message value, skipping")
                            await c.commit()
                            continue
                        if not isinstance(val, (bytes, bytearray)):
                            # unexpected type; skip and commit to avoid reprocessing
                            print(f"[ChunkIngest] unexpected message value type: {type(val)!r}, skipping")
                            await c.commit()
                            continue
                        env = decode_envelope(bytes(val))
                        # 仅处理我们关心的类型（可扩展）
                        if env.type in ("CHUNK_RECEIVED", "CHUNK_COMMITTED"):
                            await handler(env)
                        # 手动提交
                        await c.commit()
                    except Exception as e:
                        # TODO: 转发到重试/DLQ；此处仅打印
                        print(f"[ChunkIngest] handle error: {e}")
            finally:
                await c.stop()

        self._task = asyncio.create_task(_run())

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
