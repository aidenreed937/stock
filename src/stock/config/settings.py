from pathlib import Path
from typing import Any, Literal

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
    yfinance_proxy: str = ""
    yfinance_rate_limit_per_min: int = 60
    lixinger_token: str = ""
    lixinger_url: str = "https://open.lixinger.com"
    lixinger_rate_limit_per_min: int = 1000
    lxr_token: str = ""
    lxr_url: str = ""
    data_source_mode: Literal["tushare", "mock", "yfinance", "lixinger"] = "tushare"
    default_benchmark_index_code: str = "000001"
    endpoint_update_time_overrides: dict[str, str] = {}

    @property
    def effective_lixinger_token(self) -> str:
        """获取有效的理杏仁 Token（兼容 LIXINGER_TOKEN 与 LXR_TOKEN）。"""
        return self.lixinger_token or self.lxr_token

    @property
    def effective_lixinger_url(self) -> str:
        """获取有效的理杏仁 API 服务器地址。"""
        return self.lixinger_url or self.lxr_url or "https://open.lixinger.com"

    def model_post_init(self, __context: Any) -> None:
        """在初始化后加载 config/data.yaml YAML 配置文件。"""
        yaml_path = Path("config/data.yaml")
        if yaml_path.exists():
            try:
                import yaml

                with yaml_path.open("r", encoding="utf-8") as f:
                    raw_data = yaml.safe_load(f)
                if raw_data and "data" in raw_data:
                    data_cfg = raw_data["data"]
                    if (
                        "default_benchmark_index_code" in data_cfg
                        and "default_benchmark_index_code" not in self.model_fields_set
                    ):
                        object.__setattr__(
                            self,
                            "default_benchmark_index_code",
                            str(data_cfg["default_benchmark_index_code"]),
                        )
            except Exception:  # noqa: S110
                pass

    def setup_directories(self) -> None:
        """确保数据与缓存目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.curated_data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
