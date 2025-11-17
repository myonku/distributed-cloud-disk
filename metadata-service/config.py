from typing import Literal
from urllib.parse import quote_plus, urlencode

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


class RedisConfig(ConfigBase, kw_only=True):
    """Redis配置模型"""

    # 支持单节点或集群
    # mode: 单节点(single)、集群(cluster)、哨兵(sentinel)
    MODE: Literal["single", "cluster", "sentinel"] = "single"

    # 单节点兼容字段
    DIALECT: str | None = "redis"
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
                uris.append(
                    f"{self.DIALECT}://{pwd}@{hostpart}/{self.DATABASE}"
                    if pwd
                    else f"{self.DIALECT}://{hostpart}/{self.DATABASE}"
                )
            return uris

        # 回退到单节点
        if self.HOST and self.PORT is not None:
            pwd = f":{self.PASSWORD}" if self.PASSWORD else ""
            return [
                (
                    f"{self.DIALECT}://{pwd}@{self.HOST}:{self.PORT}/{self.DATABASE}"
                    if pwd
                    else f"{self.DIALECT}://{self.HOST}:{self.PORT}/{self.DATABASE}"
                )
            ]
        return []

    @property
    def redis_uri(self) -> str | None:
        """返回用于单一连接（首 URI 或 None）。"""
        uris = self.redis_uris()
        return uris[0] if uris else None


class MySQLConfig(ConfigBase, kw_only=True):
    """MySQL 配置模型（支持单节点或多主/集群形式的 HOSTS）"""

    DIALECT: str | None = "mysql"
    USER: str | None = None
    PASSWORD: str | None = None
    PORT: int | None = 3306
    HOST: str | None = None
    # 支持 host 或 host:port 列表，用于集群部署
    HOSTS: list[str] | None = None
    DATABASE: str | None = None

    def _format_conn(self, hostpart: str) -> str:
        """根据 hostpart（可能包含端口）生成与旧格式兼容的连接字符串。"""
        if ":" in hostpart:
            host, port = hostpart.split(":", 1)
        else:
            host, port = hostpart, str(self.PORT) if self.PORT is not None else ""
        user = self.USER or ""
        pwd = self.PASSWORD or ""
        db = self.DATABASE or ""
        return f"Server={host};Database={db};User Id={user};Password={pwd};Port={port}"

    def mysql_uris(self) -> list[str]:
        """返回用于连接的 MySQL 连接字符串列表（单节点返回一个，集群返回多个）。"""
        if self.HOSTS:
            return [self._format_conn(h) for h in self.HOSTS]

        if self.HOST:
            hostpart = (
                f"{self.HOST}:{self.PORT}" if self.PORT is not None else self.HOST
            )
            return [self._format_conn(hostpart)]

        return []

    @property
    def mysql_uri(self) -> str | None:
        """返回首个可用的 MySQL 连接字符串（若无则返回 None）。"""
        uris = self.mysql_uris()
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


class CryptoMiddlewareConfig(ConfigBase, kw_only=True):
    """中间件加/解密策略配置

    TOML 示例：

    [session_middleware]
    encrypt_response_paths = ["/secure/data", "/admin/secret"]
    encrypt_response_prefixes = ["/admin/"]
    require_request_encryption_paths = ["/secure/data"]
    require_request_encryption_prefixes = ["/admin/"]

    说明：
    - encrypt_response_*: 命中路径/前缀的响应将被 AES-GCM 加密（除非客户端 header 已声明）。
    - require_request_encryption_*: 命中路径/前缀的请求必须为加密形式，否则 400。
    """

    encrypt_response_paths: list[str] | None = None
    encrypt_response_prefixes: list[str] | None = None
    require_request_encryption_paths: list[str] | None = None
    require_request_encryption_prefixes: list[str] | None = None


class MongoConfig(ConfigBase, kw_only=True):
    """MongoDB连接配置"""

    DIALECT: str | None = "mongodb"
    USER: str | None = None
    PORT: int | None = None
    PASSWORD: str | None = None
    HOST: str | None = None
    # 支持 host 或 host:port 列表，用于副本集/分片（SRV 模式仅需域名，不带端口）
    HOSTS: list[str] | None = None
    DATABASE: str
    DIRECTCONNECTION: bool | None = None
    AUTHSOURCE: str | None = None
    REPLICA_SET: str | None = None
    TLS: bool | None = None
    OPTIONS: dict[str, str] | None = None

    def _host_part(self, host: str) -> str:
        if (self.DIALECT or "mongodb") == "mongodb+srv":
            return host
        if ":" in host:
            return host
        if self.PORT is not None:
            return f"{host}:{self.PORT}"
        return host

    def mongo_uris(self) -> list[str]:
        """返回用于连接的 MongoDB URI 列表（通常为单个 URI）。

        - 副本集：多个 HOSTS 逗号分隔。
        - 分片集群：连接 mongos，HOSTS 可为多个 mongos 地址或使用 mongodb+srv。
        - 单机：使用 HOST(+PORT)。
        """
        # hosts 片段
        if self.HOSTS:
            hosts_part = ",".join(self._host_part(h) for h in self.HOSTS)
        elif self.HOST:
            hosts_part = self._host_part(self.HOST)
        else:
            return []

        # 用户信息
        userinfo = ""
        if self.USER:
            if self.PASSWORD:
                userinfo = f"{quote_plus(self.USER)}:{quote_plus(self.PASSWORD)}@"
            else:
                userinfo = f"{quote_plus(self.USER)}@"

        # Query 参数
        params: dict[str, str] = {}
        if self.AUTHSOURCE:
            params["authSource"] = self.AUTHSOURCE
        if self.REPLICA_SET:
            params["replicaSet"] = self.REPLICA_SET
        if self.DIRECTCONNECTION is not None:
            params["directConnection"] = "true" if self.DIRECTCONNECTION else "false"
        if self.TLS:
            params["tls"] = "true"
        if self.OPTIONS:
            for k, v in self.OPTIONS.items():
                params[k] = str(v)

        query = "?" + urlencode(params) if params else ""
        db = self.DATABASE or ""
        dialect = self.DIALECT or "mongodb"

        uri = f"{dialect}://{userinfo}{hosts_part}/{db}{query}"
        return [uri]

    @property
    def mongo_uri(self) -> str | None:
        uris = self.mongo_uris()
        return uris[0] if uris else None


class ProjectConfig(AppConfig, kw_only=True):
    """项目配置模型"""

    API_VERSION: str = "1"
    redis: RedisConfig | None = None
    kafka: KafkaConfig | None = None
    etcd: EtcdConfig | None = None
    mysql: MySQLConfig | None = None
    mongo: MongoConfig | None = None
    middleware_cfg: CryptoMiddlewareConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    """读取应用配置"""
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config


def read_session_middleware_config(
    middleware_cfg: CryptoMiddlewareConfig | None,
) -> dict[str, object]:
    """读取并转换新的 SessionMiddleware 加/解密策略配置为中间件 load_crypto_config 可使用的 dict。

    返回结构：
    {
      "encrypt_response_paths": [...],
      "encrypt_response_prefixes": [...],
      "require_request_encryption_paths": [...],
      "require_request_encryption_prefixes": [...],
      "require_signature_on_open": true|false
    }
    若配置不存在则返回空 dict。

    兼容说明：旧版本 cred 授权字段将被忽略。
    """
    if not middleware_cfg:
        return {}
    out: dict[str, object] = {}
    if middleware_cfg.encrypt_response_paths:
        out["encrypt_response_paths"] = list(middleware_cfg.encrypt_response_paths)
    if middleware_cfg.encrypt_response_prefixes:
        out["encrypt_response_prefixes"] = list(
            middleware_cfg.encrypt_response_prefixes
        )
    if middleware_cfg.require_request_encryption_paths:
        out["require_request_encryption_paths"] = list(
            middleware_cfg.require_request_encryption_paths
        )
    if middleware_cfg.require_request_encryption_prefixes:
        out["require_request_encryption_prefixes"] = list(
            middleware_cfg.require_request_encryption_prefixes
        )
    return out
