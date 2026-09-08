"""汽车转换器兼容入口。

实现已迁移到 ``automotive.transforms.facts``，本模块保留旧导入路径。
"""

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
