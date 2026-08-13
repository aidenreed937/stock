"""金融数据集身份与 Schema 契约 (数据包兼容导出门面)。"""

from stock.core.contracts import (
    DAILY_BAR_CONTRACT,
    INDEX_DAILY_BAR_CONTRACT,
    INDEX_VALUATION_CONTRACT,
    STOCK_DAILY_BAR_CONTRACT,
    DatasetContract,
    DatasetKey,
    InstrumentId,
    instrument_for_symbol,
)
from stock.data.registry.router import dataset_for_endpoint, get_endpoint_market

__all__ = [
    "InstrumentId",
    "DatasetKey",
    "DatasetContract",
    "STOCK_DAILY_BAR_CONTRACT",
    "INDEX_DAILY_BAR_CONTRACT",
    "INDEX_VALUATION_CONTRACT",
    "DAILY_BAR_CONTRACT",
    "instrument_for_symbol",
    "get_endpoint_market",
    "dataset_for_endpoint",
]
