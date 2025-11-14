from collections.abc import Sequence
from typing import Any

from msgspec import json

from repositories.mysql_client import MySQLClient
from .models import OutboxRecord


class OutboxRepository:
    """基于 MySQL 的 Outbox 仓储实现。

    说明：
    - 表名固定为 outbox_records。
    - 采用两步锁取：单条 UPDATE 带 ORDER BY/LIMIT 选出并加锁，然后按锁标返回记录。
    - headers 以 JSON 文本存储；payload 与 key 以二进制存储。
    """

    TABLE_NAME = "outbox_records"
    COLUMNS = (
        "id, dedup_id, topic, key, partition, headers, payload, "
        "event_type, aggregate_type, aggregate_id, source, version, "
        "trace_id, tenant_id, status, attempts, next_attempt_at, "
        "locked_by, locked_at, last_error, created_at, updated_at, sent_at, priority"
    )

    def __init__(self, mysql_db: MySQLClient, table_name: str | None = None):
        self.db = mysql_db
        self.table = self.TABLE_NAME

    def _encode_headers(self, headers: dict[str, str]) -> str:
        return (json.encode(headers) if headers is not None else b"{}").decode()

    def _decode_headers(self, raw: Any) -> dict[str, str]:
        if raw is None:
            return {}
        if isinstance(raw, (bytes, bytearray, memoryview)):
            return json.decode(bytes(raw))
        if isinstance(raw, str):
            return json.decode(raw.encode())
        # 回退
        return dict(raw)

    def _row_to_record(self, row: dict[str, Any]) -> OutboxRecord:
        """将数据库行转换为 OutboxRecord 实例。"""
        key_val = row.get("key")
        payload_val = row.get("payload")
        headers_val = row.get("headers")
        return OutboxRecord(
            id=row["id"],
            dedup_id=row["dedup_id"],
            topic=row["topic"],
            key=(bytes(key_val) if key_val is not None else None),
            partition=row.get("partition"),
            headers=self._decode_headers(headers_val),
            payload=bytes(payload_val) if payload_val is not None else b"",
            event_type=row["event_type"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            source=row["source"],
            version=row["version"],
            trace_id=row.get("trace_id"),
            tenant_id=row.get("tenant_id"),
            status=row["status"],
            attempts=row["attempts"],
            next_attempt_at=row["next_attempt_at"],
            locked_by=row.get("locked_by"),
            locked_at=row.get("locked_at"),
            last_error=row.get("last_error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sent_at=row.get("sent_at"),
            priority=row["priority"],
        )

    async def insert(self, rec: OutboxRecord, *, tx=None) -> None:
        """插入一条新的 Outbox 记录。"""
        sql = f"""
        INSERT INTO {self.table}
        ({self.COLUMNS})
        VALUES
        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        args = (
            rec.id,
            rec.dedup_id,
            rec.topic,
            rec.key,
            rec.partition,
            self._encode_headers(rec.headers),
            rec.payload,
            rec.event_type,
            rec.aggregate_type,
            rec.aggregate_id,
            rec.source,
            rec.version,
            rec.trace_id,
            rec.tenant_id,
            rec.status,
            rec.attempts,
            rec.next_attempt_at,
            rec.locked_by,
            rec.locked_at,
            rec.last_error,
            rec.created_at,
            rec.updated_at,
            rec.sent_at,
            rec.priority,
        )
        if tx is not None:
            async with self.db.cursor(tx) as cur:
                await cur.execute(sql, args)
        else:
            async with self.db.connection() as conn:
                async with self.db.cursor(conn) as cur:
                    await cur.execute(sql, args)
                    await conn.commit()

    async def lock_due(
        self,
        *,
        now_epoch: float,
        limit: int,
        worker_id: str,
        lock_ttl_sec: float,
    ) -> Sequence[OutboxRecord]:
        """锁定并返回待发送的 Outbox 记录列表。"""
        lock_time = now_epoch
        expired_before = now_epoch - lock_ttl_sec

        update_sql = f"""
        UPDATE {self.table}
        SET status='SENDING', locked_by=%s, locked_at=%s, updated_at=%s
        WHERE (status='PENDING' OR status='FAILED')
          AND next_attempt_at <= %s
          AND (locked_by IS NULL OR locked_at < %s)
        ORDER BY priority DESC, next_attempt_at ASC
        LIMIT %s
        """

        select_sql = f"""
        SELECT id, dedup_id, topic, key, partition, headers, payload,
               event_type, aggregate_type, aggregate_id, source, version,
               trace_id, tenant_id, status, attempts, next_attempt_at,
               locked_by, locked_at, last_error, created_at, updated_at, sent_at, priority
        FROM {self.table}
        WHERE status='SENDING' AND locked_by=%s AND locked_at=%s
        ORDER BY priority DESC, next_attempt_at ASC
        """

        async with self.db.connection() as conn:
            # 显式事务，确保“选+锁”原子
            await conn.begin()
            async with self.db.cursor(conn) as cur:
                await cur.execute(
                    update_sql,
                    (worker_id, lock_time, lock_time, now_epoch, expired_before, limit),
                )
                # 受影响行可能 < limit
                await cur.execute(select_sql, (worker_id, lock_time))
                rows = await cur.fetchall()
            await conn.commit()

        return [self._row_to_record(r) for r in rows]

    async def mark_sent(self, rec_id: str, *, sent_at: float) -> None:
        """标记指定记录为已发送。"""
        sql = f"""
        UPDATE {self.table}
        SET status='SENT', sent_at=%s, updated_at=%s, locked_by=NULL, locked_at=NULL
        WHERE id=%s
        """
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql, (sent_at, sent_at, rec_id))
                await conn.commit()

    async def mark_failed(
        self, rec_id: str, *, error: str, attempts: int, next_attempt_at: float
    ) -> None:
        """标记指定记录为发送失败，并更新重试信息。"""
        sql = f"""
        UPDATE {self.table}
        SET status='FAILED', last_error=%s, attempts=%s, next_attempt_at=%s,
            updated_at=%s, locked_by=NULL, locked_at=NULL
        WHERE id=%s
        """
        now = next_attempt_at  # 也可用 time.time()，这里复用传入时刻
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql, (error, attempts, next_attempt_at, now, rec_id))
                await conn.commit()

    async def mark_dead(self, rec_id: str, *, error: str) -> None:
        """标记指定记录为死亡（不再重试）。"""
        sql = f"""
        UPDATE {self.table}
        SET status='DEAD', last_error=%s, updated_at=%s, locked_by=NULL, locked_at=NULL
        WHERE id=%s
        """
        from time import time as _now

        now = _now()
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql, (error, now, rec_id))
                await conn.commit()

    async def create_table_if_not_exists(self) -> None:
        """创建 Outbox 表（如果不存在）。"""
        sql = f"""
        CREATE TABLE {self.TABLE_NAME} (
            id varchar(36) NOT NULL,
            dedup_id varchar(64) NOT NULL,
            topic varchar(255) NOT NULL,
            key varbinary(1024) NULL,
            partition int NULL,
            headers json NOT NULL,
            payload longblob NOT NULL,
            event_type varchar(128) NOT NULL,
            aggregate_type varchar(128) NOT NULL,
            aggregate_id varchar(255) NOT NULL,
            source varchar(128) NOT NULL,
            version int NOT NULL,
            trace_id varchar(128) NULL,
            tenant_id varchar(128) NULL,
            status enum('PENDING','SENDING','SENT','FAILED','DEAD') NOT NULL,
            attempts int NOT NULL,
            next_attempt_at double NOT NULL,
            locked_by varchar(128) NULL,
            locked_at double NULL,
            last_error text NULL,
            created_at double NOT NULL,
            updated_at double NOT NULL,
            sent_at double NULL,
            priority int NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uniq_dedup (dedup_id),
            KEY idx_sched (status,next_attempt_at,priority)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        async with self.db.connection() as conn:
            async with self.db.cursor(conn) as cur:
                await cur.execute(sql)
                await conn.commit()
