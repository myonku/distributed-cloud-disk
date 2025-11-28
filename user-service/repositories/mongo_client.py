from typing import Any, Generic, TypeVar
from beanie import Document, init_beanie
from pydantic import BaseModel
from pymongo import AsyncMongoClient

from config import ProjectConfig
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError


class MongoDBClient:
    """MongoDB 连接管理器，集成 Beanie ODM"""

    def __init__(self):
        self.client: AsyncMongoClient | None = None
        self.is_initialized: bool = False
        self.circuit = CircuitBreaker("mongo_metadata")

    async def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            if self.client is None:
                return False

            async def _ping() -> dict:
                # server_info 本身就是一次简单的健康检查
                assert self.client is not None
                return await self.client.server_info()

            await self.circuit.call(_ping)
            return True
        except CircuitOpenError:
            # 熔断已打开，视为未连接
            return False
        except Exception:
            return False

    async def connect(self, config: ProjectConfig, document_models: list | None = None):
        """连接数据库并初始化 Beanie"""
        if not config.mongo:
            raise ConnectionError("Mongo配置初始化失败")
        print(f"正在连接MongoDB服务: {config.mongo.mongo_uri}")
        self.client = AsyncMongoClient(
            config.mongo.mongo_uri, serverSelectionTimeoutMS=3000
        )
        if document_models:
            await init_beanie(
                database=self.client[config.mongo.DATABASE],
                document_models=document_models,
            )
        self.is_initialized = True
        print(f"已连接至Mongo数据库服务[{config.mongo.DATABASE}]，Beanie 初始化已完成")

    async def disconnect(self):
        """关闭连接"""
        if self.client:
            print("正在关闭MongoDB连接")
            await self.client.close()
            self.is_initialized = False


T = TypeVar("T", bound=Document)


class MongoBaseDAO(Generic[T]):
    """基于 Beanie 的基础数据访问对象，统一做熔断包装"""

    def __init__(self, document_model: type[T]):
        self.model = document_model
        # 每个 DAO 自带一个熔断器，按模型分流
        self._circuit = CircuitBreaker(f"mongo_dao:{document_model.__name__}")

    async def get(self, id: str) -> T | None:
        """根据 ID 获取文档"""
        async def _op() -> T | None:
            return await self.model.get(id)

        return await self._circuit.call(_op)

    async def get_many(
        self, ids: list[str] | None = None, skip: int = 0, limit: int = 100
    ) -> list[T]:
        """批量查询"""
        query = {}
        if ids:
            query["_id"] = {"$in": ids}

        async def _op() -> list[T]:
            return await self.model.find(query).skip(skip).limit(limit).to_list()

        return await self._circuit.call(_op)

    async def create(self, document: T) -> T:
        """创建文档"""
        async def _op() -> T:
            return await document.insert()

        return await self._circuit.call(_op)

    async def update(self, id: str, update_data: BaseModel) -> T | None:
        """更新文档"""
        async def _op() -> T | None:
            document = await self.model.get(id)
            if document:
                update_dict = update_data.model_dump(exclude_unset=True)
                await document.set(update_dict)
                return document
            return None

        return await self._circuit.call(_op)

    async def delete(self, id: str) -> bool:
        """删除文档"""
        async def _op() -> bool:
            document = await self.model.get(id)
            if document:
                await document.delete()
                return True
            return False

        return await self._circuit.call(_op)

    async def get_many_by_field(
        self, field_name: str, value: Any, exclude_fields: list[str] | None = None
    ) -> list[T]:
        """根据字段值查询多个文档"""
        query = {field_name: value}
        async def _op() -> list[T]:
            return await self.model.find(query).to_list()

        find_query = await self._circuit.call(_op)
        docs: list[T] = []
        for q in find_query:
            doc = self.__project_attr(q, exclude_fields)
            if doc is not None:
                docs.append(doc)
        return docs

    async def get_with_projection(
        self, doc_id: str, exclude_fields: list[str] | None = None
    ) -> T | None:
        """根据ID获取文档（带字段排除）"""
        async def _op() -> T | None:
            return await self.model.get(doc_id)

        document = await self._circuit.call(_op)
        return self.__project_attr(document, exclude_fields)

    async def find_with_projection(
        self, query: Any, exclude_fields: list[str] | None = None
    ) -> list[T]:
        """根据查询条件查找文档（带字段排除）"""
        async def _op() -> list[T]:
            return await self.model.find(query).to_list()

        find_query = await self._circuit.call(_op)
        docs: list[T] = []
        for q in find_query:
            doc = self.__project_attr(q, exclude_fields)
            if doc is not None:
                docs.append(doc)
        return docs

    async def count_documents(self, query: Any) -> int:
        """计算满足查询条件的文档数量"""
        async def _op() -> int:
            return await self.model.find(query).count()

        return await self._circuit.call(_op)

    def __project_attr(
        self, document: T | None, exclude_fields: list[str] | None
    ) -> T | None:
        if not document:
            return None
        if not exclude_fields:
            return document
        for field in exclude_fields:
            if hasattr(document, field):
                setattr(document, field, None)
        return document
