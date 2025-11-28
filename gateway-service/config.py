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


class CircuitBreakerConfig:
    """熔断器配置

    - failure_threshold: 连续失败多少次后打开熔断
    - recovery_timeout: 进入 OPEN 后多长时间允许半开探测（秒）
    - half_open_max_calls: HALF_OPEN 状态下允许并发的探测调用数
    """

    failure_threshold: int = 5
    recovery_timeout: float = 10.0
    half_open_max_calls: int = 1


class RateLimitConfig(ConfigBase, kw_only=True):
    """分布式限流配置（令牌桶参数）

    - ANON_RATE / ANON_CAPACITY: 匿名（无会话）请求速率与桶容量
    - SESSION_RATE / SESSION_CAPACITY: 基于网关会话 ID 的令牌桶
    - USER_RATE / USER_CAPACITY: 基于用户 ID 的令牌桶（已登录）
    - DEVICE_RATE / DEVICE_CAPACITY: 基于设备指纹的桶（助风控）
    - COST_PER_REQUEST: 每请求消耗的令牌数量（默认 1，可在未来按路径调整）
    - ENABLE_USER_BUCKET / ENABLE_DEVICE_BUCKET: 控制是否启用对应维度
    - BLOCK_ON_EMPTY: True 时直接拒绝；False 时可进入排队/降级（此处简单直接拒绝）
    """

    ANON_RATE: float = 2.0
    ANON_CAPACITY: int = 10
    SESSION_RATE: float = 20.0
    SESSION_CAPACITY: int = 60
    USER_RATE: float = 30.0
    USER_CAPACITY: int = 90
    DEVICE_RATE: float = 10.0
    DEVICE_CAPACITY: int = 30
    COST_PER_REQUEST: int = 1
    ENABLE_USER_BUCKET: bool = True
    ENABLE_DEVICE_BUCKET: bool = True
    BLOCK_ON_EMPTY: bool = True

    def bucket_params(self, scope: str) -> tuple[float, int]:
        match scope:
            case "anon":
                return self.ANON_RATE, self.ANON_CAPACITY
            case "session":
                return self.SESSION_RATE, self.SESSION_CAPACITY
            case "user":
                return self.USER_RATE, self.USER_CAPACITY
            case "device":
                return self.DEVICE_RATE, self.DEVICE_CAPACITY
            case _:
                return self.SESSION_RATE, self.SESSION_CAPACITY


class GatewayRoutingConfig(ConfigBase, kw_only=True):
    """网关路由与访问控制配置

    用于网关中间件读取：
    - ALLOW_ANON_PATHS: 允许匿名访问的路径（无需网关会话或 cred）
    - HANDSHAKE_PATHS: 允许匿名握手的路径集合（用于端到端密钥协商的初始请求）
    - REQUIRED_CRED_RULES: 路径前缀 -> 最低 cred 规则，格式例如：
        ["/api/v1/admin:3", "/api/v1/user/profile:1", "/api/v1/user/2fa:2"]
      使用最长前缀匹配；若多个匹配取 cred 最大值（保证更严格）。
    - DEFAULT_STRATEGY: 后端实例选择默认策略（weighted_random/hash_affinity/round_robin 等占位）
    - BINDING_TTL: 后端绑定的默认存活秒数（过期后重新选择实例）
    - STICKINESS_KEY: 使用信任快照字段进行粘性路由的键（例如 user_id），为空则不启用哈希粘性
    - CANARY_TAGS: 当需要访问金丝雀/灰度实例时的标签集合（若为空则忽略标签过滤）
    """

    ALLOW_ANON_PATHS: list[str] = []
    HANDSHAKE_PATHS: list[str] = []
    REQUIRED_CRED_RULES: list[str] = []  # "/prefix:cred" 列表
    DEFAULT_STRATEGY: str = "weighted_random"
    BINDING_TTL: int = 120
    STICKINESS_KEY: str | None = "user_id"
    CANARY_TAGS: list[str] = []

    def _parse_rules(self) -> list[tuple[str, int]]:
        parsed: list[tuple[str, int]] = []
        for item in self.REQUIRED_CRED_RULES:
            try:
                path, cred_str = item.rsplit(":", 1)
                cred = int(cred_str)
                parsed.append((path.rstrip("/"), cred))
            except Exception:
                continue
        # 排序：前缀长度降序，保证最长优先（仍需取最大 cred）
        parsed.sort(key=lambda x: len(x[0]), reverse=True)
        return parsed

    @property
    def parsed_rules(self) -> list[tuple[str, int]]:
        # 缓存解析结果（简单惰性，若需更严格可用属性写时重建）
        if not hasattr(self, "_cached_rules"):
            setattr(self, "_cached_rules", self._parse_rules())
        return getattr(self, "_cached_rules")

    def min_cred_for(self, path: str) -> int:
        """计算路径所需最低 cred；未匹配返回 0 (匿名允许)。
        多规则命中时取最大 cred（保证更严格）。"""
        norm = path.rstrip("/") or "/"
        required = 0
        for prefix, cred in self.parsed_rules:
            if norm.startswith(prefix):
                if cred > required:
                    required = cred
        return required

    def is_handshake_path(self, path: str) -> bool:
        norm = path.rstrip("/") or "/"
        return any(norm == p.rstrip("/") for p in self.HANDSHAKE_PATHS)

    def is_allow_anon(self, path: str) -> bool:
        norm = path.rstrip("/") or "/"
        return any(norm == p.rstrip("/") for p in self.ALLOW_ANON_PATHS)


class ProjectConfig(AppConfig, kw_only=True):
    """项目配置模型"""

    API_VERSION: str = "1"
    # redis 支持单机或集群（请在 redis.MODE 或 redis.HOSTS 中指定）
    redis: RedisConfig | None = None
    kafka: KafkaConfig | None = None
    etcd: EtcdConfig | None = None
    mysql: MySQLConfig | None = None
    mongo: MongoConfig | None = None
    # 网关路由/访问控制配置
    routing_config: GatewayRoutingConfig | None = None
    rate_limit: RateLimitConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    """读取应用配置"""
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config
