from typing import Literal

from lihil.config import AppConfig, ConfigBase, lhl_read_config


class EtcdConfig(ConfigBase, kw_only=True):
    """Etcd 配置模型"""

    HOSTS: list[str]
    USERNAME: str | None = None
    PASSWORD: str | None = None
    TLS_ENABLED: bool = False
    CA_CERT: str | None = None
    CERT_FILE: str | None = None
    KEY_FILE: str | None = None
    NAMESPACE: str = "/dcd"


class MinIOConfig(ConfigBase, kw_only=True):
    """MinIO 客户端配置"""
    # 兼容：保留单节点字段（旧配置），并新增集群节点列表
    # 单节点（兼容旧配置）
    HOST: str | None = None
    PORT: int | None = None
    SECURE: bool = False  # https
    DEFAULT_BUCKET: str | None = None

    # 集群支持：节点列表。如果指定，则优先使用 NODES；节点会以 endpoint 列表形式返回
    class MinIONode(ConfigBase, kw_only=True):
        HOST: str
        PORT: int
        SECURE: bool = False

        @property
        def endpoint(self) -> str:
            scheme = "https" if self.SECURE else "http"
            return f"{scheme}://{self.HOST}:{self.PORT}"

    NODES: list[MinIONode] | None = None

    ACCESS_KEY: str | None = None
    SECRET_KEY: str | None = None
    REGION: str | None = None
    DEFAULT_BUCKET: str | None = None
    SIGN_EXPIRES_SECONDS: int = 900  # 预签名默认过期时间（秒）

    def endpoints(self) -> list[str]:
        """返回所有可用 endpoint（优先使用 NODES；否则回退到单节点 HOST/PORT）。"""
        if self.NODES:
            return [n.endpoint for n in self.NODES]
        if self.HOST and self.PORT is not None:
            scheme = "https" if self.SECURE else "http"
            return [f"{scheme}://{self.HOST}:{self.PORT}"]
        return []

    @property
    def endpoint(self) -> str | None:
        """返回用于单个连接的 endpoint（首节点或单节点），不存在则返回 None。"""
        eps = self.endpoints()
        return eps[0] if eps else None


class RedisConfig(ConfigBase, kw_only=True):
    """Redis配置模型"""
    # 支持单节点或集群
    # mode: 单节点(single)、集群(cluster)、哨兵(sentinel)
    MODE: Literal["single", "cluster", "sentinel"] = "single"

    # 单节点兼容字段
    DIALECT: str = "redis"
    HOST: str | None = None
    PORT: int | None = None
    PASSWORD: str | None = None
    DATABASE: int = 0

    # 集群/哨兵支持：HOSTS 列表（host:port 格式或仅 host，若仅 host 需与 PORT 一起使用）
    HOSTS: list[str] | None = None

    def redis_uris(self) -> list[str]:
        """返回用于连接的 redis URI 列表（单节点返回一个，集群返回多个）。"""
        if self.HOSTS:
            uris = []
            for h in self.HOSTS:
                # 如果 host 已经包含端口则直接使用，否则使用 PORT
                if ":" in h:
                    hostpart = h
                elif self.PORT is not None:
                    hostpart = f"{h}:{self.PORT}"
                else:
                    hostpart = h
                pwd = f":{self.PASSWORD}" if self.PASSWORD else ""
                uris.append(f"{self.DIALECT}://{pwd}@{hostpart}/{self.DATABASE}" if pwd else f"{self.DIALECT}://{hostpart}/{self.DATABASE}")
            return uris

        # 回退到单节点
        if self.HOST and self.PORT is not None:
            pwd = f":{self.PASSWORD}" if self.PASSWORD else ""
            return [f"{self.DIALECT}://{pwd}@{self.HOST}:{self.PORT}/{self.DATABASE}" if pwd else f"{self.DIALECT}://{self.HOST}:{self.PORT}/{self.DATABASE}"]
        return []

    @property
    def redis_uri(self) -> str | None:
        """返回用于单一连接（首 URI 或 None）。"""
        uris = self.redis_uris()
        return uris[0] if uris else None


class KafkaConfig(ConfigBase, kw_only=True):
    """Kafka 配置模型"""

    BOOTSTRAP_SERVERS: list[str]
    CLIENT_ID: str | None = None
    SECURITY_PROTOCOL: str | None = None  # e.g. PLAINTEXT, SASL_SSL
    SASL_MECHANISM: str | None = None
    SASL_USERNAME: str | None = None
    SASL_PASSWORD: str | None = None
    TOPIC_PREFIX: str | None = None


class ProjectConfig(AppConfig, kw_only=True):
    """项目配置模型"""

    API_VERSION: str = "1"
    # redis 支持单机或集群（请在 redis.MODE 或 redis.HOSTS 中指定）
    redis: RedisConfig | None = None
    kafka: KafkaConfig | None = None
    etcd: EtcdConfig | None = None
    minio: MinIOConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    """读取应用配置"""
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config
