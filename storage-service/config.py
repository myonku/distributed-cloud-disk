from lihil.config import AppConfig, ConfigBase, lhl_read_config


class RedisConfig(ConfigBase, kw_only=True):

    DIALECT: str
    PORT: int
    PASSWORD: str
    HOST: str
    DATABASE: int

    @property
    def redis_uri(self) -> str:
        """生成基本Redis连接字符串"""
        return f"redis://:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DATABASE}"


class ProjectConfig(AppConfig, kw_only=True):

    API_VERSION: str = "1"
    redis: RedisConfig | None = None


def read_config(*config_files: str) -> ProjectConfig:
    app_config = lhl_read_config(
        *config_files, config_type=ProjectConfig, raise_on_not_found=False
    )
    assert app_config
    return app_config
