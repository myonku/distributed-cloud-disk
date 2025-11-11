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

    DIALECT: str
    PORT: int
    PASSWORD: str
    HOST: str
    DATABASE: int

    @property
    def redis_uri(self) -> str:
        """生成基本Redis连接字符串"""
        return f"redis://:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DATABASE}"


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
    redis: RedisConfig | None = None
    kafka: KafkaConfig | None = None
    etcd: EtcdConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    """读取应用配置"""
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config
