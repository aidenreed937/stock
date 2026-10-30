"""农业产业采集器。"""

from stock_data.fetcher.industry.agriculture.collectors.mara import (
    FETCH_INTERVAL_SECONDS,
    MARA_HEADERS,
    MARA_JDSJ_ROOT,
    AgriculturePorkCollector,
    MaraPorkCrawler,
)

__all__ = [
    "FETCH_INTERVAL_SECONDS",
    "MARA_HEADERS",
    "MARA_JDSJ_ROOT",
    "AgriculturePorkCollector",
    "MaraPorkCrawler",
]
