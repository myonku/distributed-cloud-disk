from typing import Any
from msgspec import json

from repositories.mysql_client import MySQLClient
from .models import InboxProcessed


class InboxRepository:
    """基于 MySQL 的 Inbox（消费者幂等）仓储。

    表结构：见 create_table_if_not_exists。
    主键：(handler, event_id) 复合主键，保障同一处理器的同一事件只处理一次。
    """

    TABLE_NAME = "inbox_processed"

    def __init__(self, mysql_db: MySQLClient, table_name: str | None = None) -> None:
        self.db = mysql_db
        self.table = table_name or self.TABLE_NAME

    def _encode_extra(self, extra: dict[str, Any] | None) -> str | None:
        if not extra:
            return None
        return json.encode(extra).decode()

    async def create_table_if_not_exists(self) -> None:
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
            handler varchar(128) NOT NULL,
            event_id varchar(64) NOT NULL,
            aggregate_type varchar(128) NULL,
            aggregate_id varchar(255) NULL,
            tenant_id varchar(128) NULL,
            processed_at double NOT NULL,
            extra json NULL,
            PRIMARY KEY (handler, event_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql)
                await conn.commit()

    async def insert_once(self, rec: InboxProcessed, *, tx=None) -> bool:
        """尝试插入占位（若已存在则返回 False）。

        使用 INSERT IGNORE 保持语义简单；也可以改用 ON DUPLICATE KEY UPDATE 做触达统计。
        """
        sql = f"""
        INSERT IGNORE INTO {self.table}
        (handler, event_id, aggregate_type, aggregate_id, tenant_id, processed_at, extra)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """
        args = (
            rec.handler,
            rec.event_id,
            rec.aggregate_type,
            rec.aggregate_id,
            rec.tenant_id,
            rec.processed_at,
            self._encode_extra(rec.extra),
        )
        if tx is not None:
            async with self.db.cursor(tx) as cur:
                await cur.execute(sql, args)
                return cur.rowcount > 0
        else:
            async with self.db.connection() as conn:
                async with self.db.cursor(conn) as cur:
                    await cur.execute(sql, args)
                    inserted = cur.rowcount > 0
                    await conn.commit()
                    return inserted

    async def is_processed(self, handler: str, event_id: str) -> bool:
        sql = f"SELECT 1 FROM {self.table} WHERE handler=%s AND event_id=%s LIMIT 1"
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql, (handler, event_id))
                row = await cur.fetchone()
                return row is not None
