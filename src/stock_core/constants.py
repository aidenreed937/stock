"""全局常量定义模块，消除魔数与散落硬编码。"""

from typing import Final

# 核心行情 K 线数据集集合 (OHLCV 严格契约黄金表)
BAR_DATASETS: Final[frozenset[str]] = frozenset(
    {"daily_bar", "stock_daily_bar", "index_daily_bar", "fund_daily"}
)

# 模拟数据源随机种子
DEFAULT_RANDOM_SEED: Final[int] = 42

# 系统统一数据血统与元数据列集合（通用安全校验标准）
SYSTEM_METADATA_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "data_source",
        "updated_at",
        "adjustment",
        "market",
        "exchange",
        "currency",
        "schema_version",
        "source_endpoint",
        "request_id",
        "fetched_at",
        "source_id",
        "source_unit_note",
        "raw_row_count",
        "clean_row_count",
        "scope_note",
        "source_scope",
        "field_provenance",
    }
)


# 宏观风控产物中需要额外披露的退化维度。当前无此类活动指标。
MACRO_RISK_DEGRADED_MONITORS: Final[dict[str, str]] = {}

# 连续多少个交易日恒为 0 判定为「数据退化」（区别于真实单日极值 0 分位）
MACRO_RISK_DEGRADED_ZERO_RUN_DAYS: Final[int] = 3
