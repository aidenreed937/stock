"""全球海运与油运日频运价指数 (Baltic Exchange/SCFI) 数据工程子包。"""

from stock_data.fetcher.industry.shipping.collectors import ShippingCollector
from stock_data.fetcher.industry.shipping.models import ShippingIndicesRecord
from stock_data.fetcher.industry.shipping.schemas import SHIPPING_INDICES_SCHEMA
from stock_data.fetcher.industry.shipping.transforms import (
    empty_shipping_indices,
    records_to_shipping_frame,
)

__all__ = [
    "SHIPPING_INDICES_SCHEMA",
    "ShippingCollector",
    "ShippingIndicesRecord",
    "empty_shipping_indices",
    "records_to_shipping_frame",
]
