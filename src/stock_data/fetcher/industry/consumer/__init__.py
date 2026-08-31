"""大消费重点品类 (名优白酒一批价) 数据工程包。"""

from stock_data.fetcher.industry.consumer.collector import LiquorWholesaleCollector
from stock_data.fetcher.industry.consumer.transform import (
    LIQUOR_WHOLESALE_SCHEMA,
    empty_liquor_wholesale,
    records_to_liquor_wholesale_frame,
)

__all__ = [
    "LIQUOR_WHOLESALE_SCHEMA",
    "LiquorWholesaleCollector",
    "empty_liquor_wholesale",
    "records_to_liquor_wholesale_frame",
]
