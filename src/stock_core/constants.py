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
