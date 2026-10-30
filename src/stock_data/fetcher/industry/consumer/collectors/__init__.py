"""消费产业采集器。"""

from stock_data.fetcher.industry.consumer.collectors.liquor import (
    LiquorPriceCrawler,
    LiquorWholesaleCollector,
)

__all__ = ["LiquorPriceCrawler", "LiquorWholesaleCollector"]
