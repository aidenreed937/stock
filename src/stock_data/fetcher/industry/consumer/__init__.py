"""大消费重点品类 (名优白酒一批价) 数据工程包。"""

from stock_data.fetcher.industry.consumer.collectors import (
    LiquorPriceCrawler,
    LiquorWholesaleCollector,
)
from stock_data.fetcher.industry.consumer.models import LiquorWholesaleRecord
from stock_data.fetcher.industry.consumer.parsers import parse_liquor_price_text
from stock_data.fetcher.industry.consumer.schemas import LIQUOR_WHOLESALE_SCHEMA
from stock_data.fetcher.industry.consumer.transforms import (
    empty_liquor_wholesale,
    records_to_liquor_wholesale_frame,
)

__all__ = [
    "LIQUOR_WHOLESALE_SCHEMA",
    "LiquorPriceCrawler",
    "LiquorWholesaleCollector",
    "LiquorWholesaleRecord",
    "empty_liquor_wholesale",
    "parse_liquor_price_text",
    "records_to_liquor_wholesale_frame",
]
