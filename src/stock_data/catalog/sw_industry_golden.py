"""申万跨源黄金表的 DataCatalog 读取门面。"""

from stock_data.pipeline.sw_industry_golden import (
    load_sw_2021_industry_dimension,
    load_sw_2021_industry_members,
    load_sw_2021_industry_symbols,
)

__all__ = [
    "load_sw_2021_industry_dimension",
    "load_sw_2021_industry_members",
    "load_sw_2021_industry_symbols",
]
