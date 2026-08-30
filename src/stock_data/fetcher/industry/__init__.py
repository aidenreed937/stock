"""垂直产业景气与共振指标事实表转换模块。"""

from stock_data.fetcher.industry.models import (
    NevMonthlyRecord,
    SemiconductorSalesRecord,
    SolarCapacityRecord,
)
from stock_data.fetcher.industry.nev_sales import (
    NEV_MONTHLY_SCHEMA,
    empty_nev_monthly,
    records_to_nev_frame,
)
from stock_data.fetcher.industry.semiconductor_sales import (
    SEMICONDUCTOR_SALES_SCHEMA,
    empty_semiconductor_sales,
    records_to_semiconductor_frame,
)
from stock_data.fetcher.industry.solar_capacity import (
    SOLAR_CAPACITY_SCHEMA,
    empty_solar_capacity,
    records_to_solar_frame,
)

__all__ = [
    "NEV_MONTHLY_SCHEMA",
    "SEMICONDUCTOR_SALES_SCHEMA",
    "SOLAR_CAPACITY_SCHEMA",
    "NevMonthlyRecord",
    "SemiconductorSalesRecord",
    "SolarCapacityRecord",
    "empty_nev_monthly",
    "empty_semiconductor_sales",
    "empty_solar_capacity",
    "records_to_nev_frame",
    "records_to_semiconductor_frame",
    "records_to_solar_frame",
]
