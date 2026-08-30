"""有色大宗金属价格与显性库存 (SHFE/SGE/AkShare) 数据工程子包。"""

from stock_data.fetcher.industry.metals.collector import NonFerrousCollector
from stock_data.fetcher.industry.metals.transform import (
    NON_FERROUS_METALS_SCHEMA,
    empty_non_ferrous_metals,
    records_to_metals_frame,
)

__all__ = [
    "NON_FERROUS_METALS_SCHEMA",
    "NonFerrousCollector",
    "empty_non_ferrous_metals",
    "records_to_metals_frame",
]
