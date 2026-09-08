"""汽车产业 Curated/RAW 转换器。"""

from stock_data.fetcher.industry.automotive.schemas import (
    NEV_MONTHLY_RAW_SCHEMA,
    NEV_MONTHLY_SCHEMA,
)
from stock_data.fetcher.industry.automotive.transforms.facts import (
    empty_nev_monthly,
    empty_raw_nev_monthly,
    records_to_nev_frame,
    records_to_raw_nev_frame,
)

__all__ = [
    "NEV_MONTHLY_RAW_SCHEMA",
    "NEV_MONTHLY_SCHEMA",
    "empty_nev_monthly",
    "empty_raw_nev_monthly",
    "records_to_nev_frame",
    "records_to_raw_nev_frame",
]
