"""消费电子终端 (智能手机 / PC / 创新渗透率) 数据工程包。"""

from stock_data.fetcher.industry.electronics.collector import (
    ConsumerElectronicsCollector,
)
from stock_data.fetcher.industry.electronics.transform import (
    CONSUMER_ELECTRONICS_SCHEMA,
    empty_consumer_electronics,
    records_to_consumer_electronics_frame,
)

__all__ = [
    "CONSUMER_ELECTRONICS_SCHEMA",
    "ConsumerElectronicsCollector",
    "empty_consumer_electronics",
    "records_to_consumer_electronics_frame",
]
