"""航运产业 Curated 转换器。"""

from stock_data.fetcher.industry.shipping.transforms.facts import (
    empty_shipping_indices,
    records_to_shipping_frame,
)

__all__ = ["empty_shipping_indices", "records_to_shipping_frame"]
