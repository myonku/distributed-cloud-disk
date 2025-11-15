from collections.abc import Iterable
from typing import Any
from redis.asyncio import Redis, from_url
from redis.asyncio.sentinel import Sentinel
from redis.asyncio.cluster import RedisCluster, ClusterNode
from config import ProjectConfig


class RedisManager:
    """Redis 连接管理器"""

    def __init__(self):
        # 可能是 Redis、Cluster 或通过 Sentinel 获取的主库连接
        self.redis: Any | None = None
        self.is_initialized: bool = False

    def _parse_hosts(
        self, hosts: Iterable[str], default_port: int | None
    ) -> list[tuple[str, int]]:
        pairs: list[tuple[str, int]] = []
        for h in hosts:
            if ":" in h:
                host, port_s = h.rsplit(":", 1)
                pairs.append((host.strip(), int(port_s)))
            else:
                if default_port is None:
                    raise ValueError(
                        f"Port required for host '{h}' when no default PORT configured"
                    )
                pairs.append((h.strip(), int(default_port)))
        return pairs

    async def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            if self.redis is None:
                return False
            # 统一用 PING 验证
            pong = await self.redis.ping()
            return bool(pong)
        except Exception:
            return False

    async def connect(self, config: ProjectConfig, **kwargs):
        """连接 Redis"""
        if not config.redis:
            raise ConnectionError("Redis配置初始化失败")
        mode = (
            config.redis.MODE if hasattr(config.redis, "MODE") else "single"
        ).lower()

        # 通用连接参数（single/cluster 下使用）
        common_kwargs = {
            "encoding": "utf-8",
            "decode_responses": True,
            "max_connections": 100,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
        }
        common_kwargs.update(kwargs)

        if mode == "single":
            if not config.redis.redis_uri:
                raise ValueError("单机模式下缺少 redis_uri")
            print(f"正在连接Redis(单机): {config.redis.redis_uri}")
            self.redis = from_url(config.redis.redis_uri, **common_kwargs)
            self.is_initialized = True
            print("Redis(单机)连接完成")
            return

        if mode == "sentinel":
            if Sentinel is None:
                raise RuntimeError("未安装 redis-py sentinel 组件，无法使用哨兵模式")
            if not config.redis.HOSTS:
                raise ValueError("哨兵模式需要提供 redis.HOSTS 列表")
            sentinel_service_name: str = kwargs.pop("sentinel_service_name", "mymaster")
            pairs = self._parse_hosts(
                config.redis.HOSTS, default_port=config.redis.PORT
            )
            print(f"正在连接Redis(Sentinel): {pairs} service={sentinel_service_name}")
            sentinel = Sentinel(
                pairs,
                socket_timeout=5,
                password=(
                    config.redis.PASSWORD
                    if getattr(config.redis, "PASSWORD", None)
                    else None
                ),
            )
            # master_for 返回一个 Redis 连接对象（自动主从切换）
            self.redis = sentinel.master_for(
                service_name=sentinel_service_name,
                decode_responses=common_kwargs.get("decode_responses", True),
                socket_timeout=common_kwargs.get("socket_timeout", 5),
                socket_connect_timeout=common_kwargs.get("socket_connect_timeout", 5),
                max_connections=common_kwargs.get("max_connections", 100),
                password=(
                    config.redis.PASSWORD
                    if getattr(config.redis, "PASSWORD", None)
                    else None
                ),
            )
            self.is_initialized = True
            print("Redis(Sentinel)连接完成")
            return

        if mode == "cluster":
            if RedisCluster is None:
                raise RuntimeError("未安装 redis-py cluster 组件，无法使用集群模式")
            if not config.redis.HOSTS:
                raise ValueError("集群模式需要提供 redis.HOSTS 列表")
            pairs = self._parse_hosts(
                config.redis.HOSTS, default_port=config.redis.PORT
            )
            startup_nodes = [
                ClusterNode(
                    h,
                    p,
                )
                for h, p in pairs
            ]
            print(f"正在连接Redis(Cluster): {startup_nodes}")
            # RedisCluster 参数名保持与 redis-py 对齐
            self.redis = RedisCluster(
                startup_nodes=startup_nodes,
                decode_responses=common_kwargs.get("decode_responses", True),
                socket_timeout=common_kwargs.get("socket_timeout", 5),
                socket_connect_timeout=common_kwargs.get("socket_connect_timeout", 5),
                max_connections=common_kwargs.get("max_connections", 200),
                password=getattr(config.redis, "PASSWORD", None),
            )
            self.is_initialized = True
            print("Redis(Cluster)连接完成")
            return

        raise ValueError(f"不支持的 Redis 模式: {mode}")

    async def disconnect(self):
        """关闭连接"""
        if self.redis:
            print("正在关闭Redis连接")
            await self.redis.close()
            self.redis = None
            self.is_initialized = False

    def get_client(self) -> Redis:
        """获取 Redis 客户端"""
        if self.redis is None:
            raise RuntimeError("Redis未初始化")
        return self.redis
