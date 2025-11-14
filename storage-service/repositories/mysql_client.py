from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
import aiomysql


class MySQLClient:
    """
    MySQL 异步客户端，封装了连接池和基本的数据库操作。
    为业务/元数据服务和OutBox提供服务引用。
    """
    def __init__(self):
        self.pool: aiomysql.Pool | None = None

    async def is_connected(self) -> bool:
        return self.pool is not None and not self.pool.closed

    async def connect(self, host: str, port: int, user: str, password: str, db: str):
        print(
            f"正在连接MySQL服务: Server={host};Database={db};User Id={user};Password={password};Port={port}"
        )
        self.pool = await aiomysql.create_pool(
            host=host, port=port, user=user, password=password, db=db
        )
        print(f"已连接至MySQL数据库: {db}")

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
        try:
            async with self.mysql_db.cursor() as cur:
                await cur.execute(query, params)
                conn: Any = cur.connection
                await conn.commit()
        except Exception as e:
            print(f"MySQL query failed: {query} | {params} | {e}")
            raise

    async def _fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()

    async def _fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        async with self.mysql_db.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()

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
