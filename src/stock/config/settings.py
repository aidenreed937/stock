from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用配置类，从环境变量或 .env 文件读取配置。"""

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
    raw_data_dir: Path = Path("./data/raw")
    curated_data_dir: Path = Path("./data/curated")
    cache_dir: Path = Path("./data/cache")

    tushare_token: str = ""
    tushare_url: str = "http://api.tushare.pro"
    tushare_rate_limit_per_min: int = 200
    tushare_max_workers: int = 4
    akshare_proxy: str = ""
    data_source_mode: str = "mock"

    def setup_directories(self) -> None:
        """确保数据与缓存目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.curated_data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
