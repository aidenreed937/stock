"""全局常量定义模块，消除魔数与散落硬编码。"""

from typing import Final

# 默认技术指标周期
DEFAULT_SMA_WINDOW: Final[int] = 5
DEFAULT_EMA_WINDOW: Final[int] = 12
DEFAULT_RSI_WINDOW: Final[int] = 14

# 存储层与路径相关常量
DEFAULT_PARQUET_SUBDIR: Final[str] = "parquet"

# 核心行情 K 线数据集集合 (OHLCV 严格契约黄金表)
BAR_DATASETS: Final[frozenset[str]] = frozenset(
    {"daily_bar", "stock_daily_bar", "index_daily_bar", "fund_daily"}
)

# 模拟数据源随机种子
DEFAULT_RANDOM_SEED: Final[int] = 42

# 接口历史最早数据起始日校准表：自动将更早的无意义请求截断提升至真实上线首日
ENDPOINT_START_DATE_OVERRIDES: Final[dict[str, str]] = {
    "moneyflow_hsgt": "2014-11-17",
    "hsgt_top10": "2014-11-17",
    "margin": "2010-03-31",
    "fund_daily": "1998-04-07",
    "sw_daily": "2014-01-02",
}

# 交易所特定业务上线首日表：精准拦截早于交易所上线时间的无用 API 请求
EXCHANGE_START_DATES: Final[dict[str, dict[str, str]]] = {
    "margin": {
        "SSE": "2010-03-31",
        "SZSE": "2010-03-31",
        "BSE": "2023-02-13",
    }
}
