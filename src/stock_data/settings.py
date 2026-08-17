"""数据管道专用的环境变量、密钥与路径配置。"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSettings(BaseSettings):
    """数据管道专用的环境变量与密钥配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 存储与目录配置
    data_dir: Path = Path("./data")
    raw_data_dir: Path = Path("./data/raw")
    curated_data_dir: Path = Path("./data/curated")
    cache_dir: Path = Path("./data/cache")

    # TuShare 密钥与配置
    tushare_token: str = ""
    tushare_url: str = "http://api.tushare.pro"

    # 理杏仁密钥与配置
    lixinger_token: str = ""
    lixinger_url: str = "https://open.lixinger.com"
    lxr_token: str = ""
    lxr_url: str = ""

    # FRED 密钥
    fred_api_key: str = ""

    # Alpha Vantage 密钥与配置
    alpha_vantage_api_key: str = ""
    alpha_vantage_url: str = "https://www.alphavantage.co/query"
    alpha_vantage_proxy: str = ""

    # 代理配置
    akshare_proxy: str = ""
    yfinance_proxy: str = ""
    yfinance_proxy_pool_file: Path = Path("data/proxy")

    # 默认数据源模式
    data_source_mode: Literal["tushare", "yfinance", "lixinger", "fred", "alphavantage"] = "tushare"
    endpoint_update_time_overrides: dict[str, str] = {}

    @property
    def effective_lixinger_token(self) -> str:
        """获取有效的理杏仁 Token（兼容 LIXINGER_TOKEN 与 LXR_TOKEN）。"""
        return self.lixinger_token or self.lxr_token

    @property
    def effective_lixinger_url(self) -> str:
        """获取有效的理杏仁 API 服务器地址。"""
        return self.lixinger_url or self.lxr_url or "https://open.lixinger.com"

    def setup_directories(self) -> None:
        """确保数据与缓存目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.curated_data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


data_settings = DataSettings()
