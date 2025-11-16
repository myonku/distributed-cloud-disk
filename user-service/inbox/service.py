from typing import Any
from collections.abc import Callable, Awaitable

from repositories.mysql_client import MySQLClient
from .models import InboxProcessed
from .repo import InboxRepository


class InboxService:
    """提供消费者侧“有效一次处理”封装。

    用法：
        svc = InboxService(mysql_client)
        await svc.process_once(
            handler="user-service:USER_CREATED",
            event_id=envelope.event_id,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            tenant_id=envelope.headers.get("tenant_id"),
            extra={"topic": topic},
            process=lambda conn: do_business(conn, envelope),
        )
    """

    def __init__(self, mysql_db: MySQLClient, table_name: str | None = None) -> None:
        self.db = mysql_db
        self.repo = InboxRepository(mysql_db, table_name)

    async def ensure_table(self) -> None:
        await self.repo.create_table_if_not_exists()

    async def process_once(
        self,
        *,
        handler: str,
        event_id: str,
        process: Callable[[Any], Awaitable[None]],
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        tenant_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """在单事务内完成幂等占位与业务处理。

        返回：True 表示本次为首次处理且已执行业务；False 表示已处理过而跳过。
        """
        marker = InboxProcessed.new(
            handler=handler,
            event_id=event_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            tenant_id=tenant_id,
            extra=extra,
        )
        async with self.db.connection() as conn:
            await conn.begin()
            # 占位（若已存在则 rowcount=0）
            inserted = await self.repo.insert_once(marker, tx=conn)
            if not inserted:
                await conn.commit()
                return False
            # 执行业务逻辑（使用同一连接，便于端到端事务一致）
            await process(conn)
            await conn.commit()
            return True
