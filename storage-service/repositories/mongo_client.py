from beanie import init_beanie
from pymongo import AsyncMongoClient

from config import ProjectConfig


class MongoDBClient:
    """MongoDB 连接管理器，集成 Beanie ODM"""

    def __init__(self):
        self.client: AsyncMongoClient | None = None
        self.is_initialized: bool = False

    async def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            if self.client is None:
                return False
            await self.client.server_info()
            return True
        except:
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

