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


class SessionMiddlewareConfig(ConfigBase, kw_only=True):
    """Session 中间件访问与响应加密策略配置

    TOML 示例：

    [session_middleware]
    encrypt_response_paths = ["/secure/data", "/admin/secret"]

    [session_middleware.required_cred_exact]
    "/user/profile" = 1
    "/user/settings" = 1

    [[session_middleware.required_cred_prefix]]
    prefix = "/admin/"
    cred = 3

    [[session_middleware.required_cred_by_method]]
    method = "POST"
    path = "/user/transfer"
    cred = 2

    [[session_middleware.required_cred_prefix_by_method]]
    method = "DELETE"
    prefix = "/user/"
    cred = 2
    """

    class SessionCredPrefix(ConfigBase, kw_only=True):
        prefix: str
        cred: int

    class SessionCredByMethod(ConfigBase, kw_only=True):
        method: str
        path: str
        cred: int

    class SessionCredPrefixByMethod(ConfigBase, kw_only=True):
        method: str
        prefix: str
        cred: int

    encrypt_response_paths: list[str] | None = None
    required_cred_exact: dict[str, int] | None = None
    required_cred_prefix: list[SessionCredPrefix] | None = None
    required_cred_by_method: list[SessionCredByMethod] | None = None
    required_cred_prefix_by_method: list[SessionCredPrefixByMethod] | None = None


class ProjectConfig(AppConfig, kw_only=True):
    """项目配置模型"""

    API_VERSION: str = "1"
    redis: RedisConfig | None = None
    kafka: KafkaConfig | None = None
    etcd: EtcdConfig | None = None
    mysql: MySQLConfig | None = None
    session_middleware: SessionMiddlewareConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    """读取应用配置"""
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config


def read_session_middleware_config(
    sm_cfg: SessionMiddlewareConfig | None,
) -> dict[str, object]:
    """读取并转换 SessionMiddleware 配置为中间件可直接 load_access_config 使用的 dict。

    返回结构与 SessionMiddleware.load_access_config 期望一致：
    {
      "encrypt_response_paths": [...],
      "required_cred_exact": {...},
      "required_cred_prefix": [{"prefix":"/admin/","cred":3}],
      "required_cred_by_method": [{"method":"POST","path":"/x","cred":2}],
      "required_cred_prefix_by_method": [{"method":"DELETE","prefix":"/user/","cred":2}]
    }
    若配置不存在则返回空 dict。
    """
    if not sm_cfg:
        return {}
    out: dict[str, object] = {}
    if sm_cfg.encrypt_response_paths:
        out["encrypt_response_paths"] = list(sm_cfg.encrypt_response_paths)
    if sm_cfg.required_cred_exact:
        out["required_cred_exact"] = dict(sm_cfg.required_cred_exact)
    if sm_cfg.required_cred_prefix:
        out["required_cred_prefix"] = [
            {"prefix": p.prefix, "cred": p.cred} for p in sm_cfg.required_cred_prefix
        ]
    if sm_cfg.required_cred_by_method:
        out["required_cred_by_method"] = [
            {"method": r.method, "path": r.path, "cred": r.cred}
            for r in sm_cfg.required_cred_by_method
        ]
    if sm_cfg.required_cred_prefix_by_method:
        out["required_cred_prefix_by_method"] = [
            {"method": r.method, "prefix": r.prefix, "cred": r.cred}
            for r in sm_cfg.required_cred_prefix_by_method
        ]
    return out
