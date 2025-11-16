import asyncio
from collections.abc import Callable, Awaitable
from typing import Any

from kafka.kafka_client import KafkaClient
from ..models import EventEnvelope, decode_envelope
from inbox.service import InboxService
from repositories.mysql_client import MySQLClient

TOPIC_USER_EVENTS = "dcd.user.events.v1"


class UserEventsConsumer:
    """消费用户域事件（USER_CREATED/USER_DELETED），以 Inbox 保证幂等并安全提交 offset"""

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
        self.handler_id = handler_id
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, handler: Callable[[Any, EventEnvelope], Awaitable[None]]) -> None:
        await self.inbox.ensure_table()

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
                        if env.type not in ("USER_CREATED", "USER_DELETED"):
                            await c.commit()
                            continue

                        handler_key = self.handler_id or f"{self.group_id}:{TOPIC_USER_EVENTS}|{env.type}"

                        async def do_business(conn):
                            await handler(conn, env)

                        _ = await self.inbox.process_once(
                            handler=handler_key,
                            event_id=env.event_id,
                            aggregate_type=env.aggregate_type,
                            aggregate_id=env.aggregate_id,
                            tenant_id=(env.headers or {}).get("tenant_id"),
                            extra={"partition": msg.partition, "offset": msg.offset},
                            process=do_business,
                        )

                        await c.commit()
                    except Exception as e:
                        # TODO: retry/DLQ
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