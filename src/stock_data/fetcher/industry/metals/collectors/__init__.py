"""有色金属产业采集器。"""

from stock_data.fetcher.industry.metals.collectors.akshare import (
    NonFerrousCollector,
    fetch_akshare_metals_data,
)

__all__ = ["NonFerrousCollector", "fetch_akshare_metals_data"]
