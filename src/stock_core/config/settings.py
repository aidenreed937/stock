"""全局应用与运行时环境配置。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用基础配置类，从环境变量或 .env 文件读取配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StockFinanceApp"
    environment: str = "development"
    log_level: str = "INFO"
    log_retention_days: int = 14
    log_rotation_size: str = "10 MB"
    data_dir: Path = Path("./data")


settings = Settings()
