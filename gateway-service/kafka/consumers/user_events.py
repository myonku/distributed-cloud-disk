import asyncio
from collections.abc import Callable, Awaitable
from typing import Any

from kafka.kafka_client import KafkaClient
from inbox.service import InboxService
from repositories.mysql_client import MySQLClient
from ..models import EventEnvelope, decode_envelope

TOPIC_USER_EVENTS = "dcd.user.events.v1"


class UserEventsConsumer:
    """消费用户域事件（USER_LOGGED_IN / USER_LOGGED_OUT / SESSION_REVOKED）并进行幂等处理。

    使用 InboxService 保证事件处理按 (handler_key, event_id) 去重：
    - 首次处理：执行业务逻辑并记录
    - 重复收到：快速跳过仍然提交 offset

    handler 形参：`handler(conn, envelope)`，其中 conn 为 MySQL 连接/事务上下文。
    """

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
        self.handler_id = handler_id  # 可自定义处理器标识，便于多类型消费者隔离
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, handler: Callable[[Any, EventEnvelope], Awaitable[None]]) -> None:
        # 确保 Inbox 元数据表已存在
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
                            print("[UserEvents] bad value, skipping")
                            await c.commit()
                            continue

                        env = decode_envelope(bytes(val))
                        if env.type not in (
                            "USER_LOGGED_IN",
                            "USER_LOGGED_OUT",
                            "SESSION_REVOKED",
                        ):
                            # 非目标事件：提交 offset 直接跳过
                            await c.commit()
                            continue

                        # 组合 handler key（同一消费组/同类消费者共享，利于跨实例幂等）
                        handler_key = self.handler_id or f"{self.group_id}:{TOPIC_USER_EVENTS}|{env.type}"

                        async def do_business(conn):
                            # 业务建议使用幂等 SQL，如 INSERT ... ON DUPLICATE KEY UPDATE
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

                        # 到此说明处理成功或已处理，安全提交 offset
                        await c.commit()
                    except Exception as e:
                        # TODO: 转发到重试 / DLQ（带上 event_id、分区、偏移）
                        print(f"[UserEvents] handle error: {e}")
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
