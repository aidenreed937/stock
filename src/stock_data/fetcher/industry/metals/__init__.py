"""有色大宗金属价格与显性库存 (SHFE/SGE/AkShare) 数据工程子包。"""

from stock_data.fetcher.industry.metals.collectors import NonFerrousCollector
from stock_data.fetcher.industry.metals.models import NonFerrousMetalsRecord
from stock_data.fetcher.industry.metals.schemas import NON_FERROUS_METALS_SCHEMA
from stock_data.fetcher.industry.metals.transforms import (
    empty_non_ferrous_metals,
    records_to_metals_frame,
)

__all__ = [
    "NON_FERROUS_METALS_SCHEMA",
    "NonFerrousCollector",
    "NonFerrousMetalsRecord",
    "empty_non_ferrous_metals",
    "records_to_metals_frame",
]
