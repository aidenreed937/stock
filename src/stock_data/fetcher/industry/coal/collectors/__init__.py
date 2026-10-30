"""煤炭产业采集器。"""

from stock_data.fetcher.industry.coal.collectors.cctd import (
    CCTD_HEADERS,
    CCTD_URL,
    CoalMarketCollector,
    CoalMarketCrawler,
)

__all__ = ["CCTD_HEADERS", "CCTD_URL", "CoalMarketCollector", "CoalMarketCrawler"]
