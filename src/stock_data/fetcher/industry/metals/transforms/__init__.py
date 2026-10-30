"""有色金属产业 Curated 转换器。"""

from stock_data.fetcher.industry.metals.transforms.facts import (
    empty_non_ferrous_metals,
    records_to_metals_frame,
)

__all__ = ["empty_non_ferrous_metals", "records_to_metals_frame"]
