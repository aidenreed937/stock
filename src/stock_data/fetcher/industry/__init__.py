"""垂直产业景气指标采集器与事实表转换模块。"""

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    save_curated_fact,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.models import (
    NevMonthlyRecord,
    SemiconductorSalesRecord,
    SolarCapacityRecord,
)
from stock_data.fetcher.industry.nev import NevCollector
from stock_data.fetcher.industry.nev_sales import (
    NEV_MONTHLY_SCHEMA,
    empty_nev_monthly,
    records_to_nev_frame,
)
from stock_data.fetcher.industry.pipeline import sync_all_industry_metrics
from stock_data.fetcher.industry.semiconductor import SemiconductorCollector
from stock_data.fetcher.industry.semiconductor_sales import (
    SEMICONDUCTOR_SALES_SCHEMA,
    empty_semiconductor_sales,
    records_to_semiconductor_frame,
)
from stock_data.fetcher.industry.solar import SolarCollector
from stock_data.fetcher.industry.solar_capacity import (
    SOLAR_CAPACITY_SCHEMA,
    empty_solar_capacity,
    records_to_solar_frame,
)

__all__ = [
    "NEV_MONTHLY_SCHEMA",
    "SEMICONDUCTOR_SALES_SCHEMA",
    "SOLAR_CAPACITY_SCHEMA",
    "NevCollector",
    "NevMonthlyRecord",
    "SemiconductorCollector",
    "SemiconductorSalesRecord",
    "SolarCapacityRecord",
    "SolarCollector",
    "empty_nev_monthly",
    "empty_semiconductor_sales",
    "empty_solar_capacity",
    "get_month_end_date",
    "records_to_nev_frame",
    "records_to_semiconductor_frame",
    "records_to_solar_frame",
    "save_curated_fact",
    "save_raw_snapshot",
    "sync_all_industry_metrics",
]
