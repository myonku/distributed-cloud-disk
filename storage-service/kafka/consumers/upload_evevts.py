import asyncio
from collections.abc import Callable, Awaitable
from typing import Any
from kafka.kafka_client import KafkaClient
from inbox.service import InboxService
from repositories.mysql_client import MySQLClient
from ..models import EventEnvelope, decode_envelope

TOPIC_CHUNK_EVENTS = "dcd.chunk.events.v1"


class ChunkIngestConsumer:
    """消费存储节点的分片事件（CHUNK_RECEIVED 等），推进上传会话状态"""

    def __init__(
        self,
        kc: KafkaClient,
        group_id: str,
        bootstrap_servers: list[str],
        mysql: MySQLClient,
        handler_id: str | None = None,
    ) -> None:
        self.kc = kc
        self.group_id = group_id
        self.bootstrap_servers = bootstrap_servers
        self.mysql = mysql
        self.inbox = InboxService(mysql)
        self.handler_id = handler_id  # 可自定义处理器标识
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, handler: Callable[[Any, EventEnvelope], Awaitable[None]]):
        await self.inbox.ensure_table()

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
                        if not isinstance(val, (bytes, bytearray)):
                            print("[ChunkIngest] bad value, skipping")
                            await c.commit()
                            continue

                        env = decode_envelope(bytes(val))
                        if env.type not in ("CHUNK_RECEIVED", "CHUNK_COMMITTED"):
                            await c.commit()
                            continue

                        # 组合 handler key（同一消费组/同类消费者共享同一 key 才能跨实例去重）
                        handler_key = (
                            self.handler_id
                            or f"{self.group_id}:{TOPIC_CHUNK_EVENTS}|{env.type}"
                        )

                        # 定义业务处理（事务内执行）
                        async def do_business(conn):
                            await handler(
                                conn, env
                            )  # 建议业务用 conn 执行 SQL（幂等 upsert）

                        # 幂等占位 + 业务处理
                        _ = await self.inbox.process_once(
                            handler=handler_key,
                            event_id=env.event_id,
                            aggregate_type=env.aggregate_type,
                            aggregate_id=env.aggregate_id,
                            tenant_id=(env.headers or {}).get("tenant_id"),
                            extra={"partition": msg.partition, "offset": msg.offset},
                            process=do_business,
                        )
                        # 首次或重复，到了这里都代表处理成功或已处理，安全提交 offset
                        await c.commit()

                    except Exception as e:
                        # TODO: 转发到重试/DLQ（带上 env.event_id/分区/偏移等），此处仅打印且不提交 offset
                        print(f"[ChunkIngest] handle error: {e}")
            finally:
                await c.stop()

        self._task = asyncio.create_task(_run())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
