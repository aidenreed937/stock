"""消费产业源端解析器。"""

from stock_data.fetcher.industry.consumer.parsers.liquor import (
    JINRIJIA_URL,
    parse_liquor_price_text,
)
from stock_data.fetcher.industry.consumer.parsers.raw_csv import (
    LIQUOR_PRICE_FIELDNAMES,
    load_liquor_raw_csv,
    save_liquor_raw_csv,
)

__all__ = [
    "JINRIJIA_URL",
    "LIQUOR_PRICE_FIELDNAMES",
    "load_liquor_raw_csv",
    "parse_liquor_price_text",
    "save_liquor_raw_csv",
]
