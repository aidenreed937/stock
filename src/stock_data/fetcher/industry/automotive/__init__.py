"""新能源汽车月度产销与渗透率 (CPCA/CAAM) 数据工程子包。"""

from stock_data.fetcher.industry.automotive.collector import NevCollector
from stock_data.fetcher.industry.automotive.transform import (
    NEV_MONTHLY_SCHEMA,
    empty_nev_monthly,
    records_to_nev_frame,
)

__all__ = [
    "NEV_MONTHLY_SCHEMA",
    "NevCollector",
    "empty_nev_monthly",
    "records_to_nev_frame",
]
