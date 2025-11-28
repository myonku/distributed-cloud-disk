from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aiomysql
from config import ProjectConfig, MySQLConfig
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError



class MySQLClient:
    """
    MySQL 异步客户端，封装了连接池和基本的数据库操作。
    为业务/元数据服务和OutBox提供服务引用。
    """
    def __init__(self):
        self.pool: aiomysql.Pool | None = None
        self.circuit = CircuitBreaker("mysql_metadata")

    async def is_connected(self) -> bool:
        return self.pool is not None and not self.pool.closed

    def _parse_conn_str(self, conn_str: str) -> dict[str, str]:
        """解析形如 'Server=host;Database=db;User Id=u;Password=p;Port=3306' 的连接字符串。
        注意：简单分号分割，不支持带分号的密码。
        """
        parts = [p for p in conn_str.split(";") if p.strip()]
        kv: dict[str, str] = {}
        for p in parts:
            if "=" not in p:
                continue
            k, v = p.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        return kv

    async def connect(self, cfg: ProjectConfig | MySQLConfig, **pool_kwargs: Any):
        """基于配置连接：
        - 若提供多个 URI（HOSTS），按顺序尝试连接到第一个可用实例。
        - 若仅单个 URI，则直接连接。
        - 建议生产中使用 MySQL Router/ProxySQL 暴露单一入口。
        """
        mysql_cfg: MySQLConfig | None
        if isinstance(cfg, ProjectConfig):
            mysql_cfg = getattr(cfg, "mysql", None)
        else:
            mysql_cfg = cfg

        if not mysql_cfg:
            raise RuntimeError("MySQL config not provided")

        uris = mysql_cfg.mysql_uris()
        if not uris:
            raise RuntimeError("MySQL connection strings are empty")

        last_err: Exception | None = None
        for conn_str in uris:
            kv = self._parse_conn_str(conn_str)
            host = kv.get("server") or kv.get("host") or ""
            db = kv.get("database") or kv.get("db") or ""
            user = kv.get("user id") or kv.get("uid") or kv.get("user") or ""
            password = kv.get("password") or kv.get("pwd") or ""
            port_s = kv.get("port") or ""
            try:
                port = int(port_s) if port_s else (mysql_cfg.PORT or 3306)
                await self.connect(host=host, port=port, user=user, password=password, db=db, **pool_kwargs)
                return
            except Exception as e:  # 尝试下一个
                last_err = e
                print(f"连接失败，尝试下一个 MySQL 实例: {conn_str} | {e}")
                continue

        raise ConnectionError(f"所有 MySQL 实例连接失败: {last_err}")

    async def disconnect(self):
        print("正在关闭MySQL连接")
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiomysql.Connection, None]:
        """提供一个异步上下文管理器，获取一个数据库连接。"""
        if not self.pool:
            raise RuntimeError("MySQL connection pool not initialized")
        async with self.pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def cursor(
        self, conn: aiomysql.Connection | None = None
    ) -> AsyncGenerator[aiomysql.Cursor, None]:
        """提供一个异步上下文管理器，获取一个 DictCursor 游标。"""
        if conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield cur
        else:
            async with self.connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    yield cur


class MySQLBaseDAO:
    """MySQL DAO基类，对MySQLClient进行封装，提供通用CRUD操作"""

    def __init__(self, mysql_db: MySQLClient, table_name: str):
        self.mysql_db = mysql_db
        self.table_name = table_name

    async def _execute(self, query: str, params: tuple = ()):
        async def _do_exec() -> None:
            async with self.mysql_db.cursor() as cur:
                await cur.execute(query, params)
                conn: Any = cur.connection
                await conn.commit()

        try:
            await self.mysql_db.circuit.call(_do_exec)
        except CircuitOpenError as e:
            # 熔断打开时的快速失败日志，可按需要接入监控/告警
            print(f"MySQL circuit open, fast-fail execute: {query} | {params} | {e}")
            raise
        except Exception as e:
            print(f"MySQL query failed: {query} | {params} | {e}")
            raise

    async def _fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        async def _do_fetch_one() -> dict | None:
            async with self.mysql_db.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

        try:
            return await self.mysql_db.circuit.call(_do_fetch_one)
        except CircuitOpenError as e:
            print(f"MySQL circuit open, fast-fail fetch_one: {query} | {params} | {e}")
            raise

    async def _fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        async def _do_fetch_all() -> list[dict]:
            async with self.mysql_db.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

        try:
            return await self.mysql_db.circuit.call(_do_fetch_all)
        except CircuitOpenError as e:
            print(f"MySQL circuit open, fast-fail fetch_all: {query} | {params} | {e}")
            raise

    async def get(self, id: str) -> dict | None:
        """根据id查询单条数据"""
        query = f"SELECT * FROM {self.table_name} WHERE id = %s"
        return await self._fetch_one(query, (id,))

    async def get_many(
        self,
        id_list: list[str] | None = None,
        limit: int = 0,
        skip: int = 0,
        qry: dict[Any, Any] | None = None,
    ) -> list[dict]:
        """批量查询，支持筛选和分页"""
        base_query = f"SELECT * FROM {self.table_name}"
        conditions = []
        params = []

        if id_list:
            conditions.append("id IN %s")
            params.append(tuple(id_list))

        if qry:
            for key, value in qry.items():
                conditions.append(f"{key} = %s")
                params.append(value)

        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)

        if limit > 0:
            base_query += f" LIMIT {limit}"

        if skip > 0:
            base_query += f" OFFSET {skip}"

        return await self._fetch_all(base_query, tuple(params))

    async def create(self, data: dict) -> str:
        """单条插入"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"""
            INSERT INTO {self.table_name} ({columns})
            VALUES ({placeholders})
        """
        params = tuple(data.values())

        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, params)
            conn: Any = cur.connection
            await conn.commit()
            return data["id"]

    async def create_many(self, data_list: list[dict]) -> list[str]:
        """批量插入"""
        if not data_list:
            return []

        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join(["%s"] * len(data_list[0]))
        query = f"""
            INSERT INTO {self.table_name} ({columns})
            VALUES ({placeholders})
        """
        params = [tuple(data.values()) for data in data_list]

        async with self.mysql_db.cursor() as cur:
            await cur.executemany(query, params)
            conn: Any = cur.connection
            await conn.commit()
            return [data["id"] for data in data_list]

    async def update(self, id: str, update: dict) -> bool:
        """更新单条数据的某些字段"""
        if not update:
            return False

        set_clause = ", ".join([f"{key} = %s" for key in update.keys()])
        query = f"""
            UPDATE {self.table_name}
            SET {set_clause}
            WHERE id = %s
        """
        params = tuple(update.values()) + (id,)

        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, params)
            conn: Any = cur.connection
            await conn.commit()
            return cur.rowcount > 0

    async def update_many(self, ids: list[str], update: dict) -> bool:
        """更新所有符合条件的文档的某些字段"""
        if not update or not ids:
            return False

        set_clause = ", ".join([f"{key} = %s" for key in update.keys()])
        query = f"""
            UPDATE {self.table_name}
            SET {set_clause}
            WHERE id IN %s
        """
        params = tuple(update.values()) + (tuple(ids),)

        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, params)
            conn: Any = cur.connection
            await conn.commit()
            return cur.rowcount > 0

    async def delete(self, id: str) -> bool:
        """删除单条数据"""
        query = f"DELETE FROM {self.table_name} WHERE id = %s"
        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, (id,))
            conn: Any = cur.connection
            await conn.commit()
            return cur.rowcount > 0

    async def delete_many(self, ids: list[str]) -> bool:
        """删除所有符合条件的文档"""
        if not ids:
            return False

        query = f"DELETE FROM {self.table_name} WHERE id IN %s"
        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, (tuple(ids),))
            conn: Any = cur.connection
            await conn.commit()
            return cur.rowcount > 0
