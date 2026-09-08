"""汽车产业端点注册。"""

from stock_data.fetcher.industry.automotive.collectors.nev import NevCollector
from stock_data.fetcher.industry.automotive.paths import AUTOMOTIVE_RAW_SUBDIR
from stock_data.fetcher.industry.automotive.transforms import (
    records_to_nev_frame,
    records_to_raw_nev_frame,
)
from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="nev_monthly_sales",
        domain="automotive",
        collect=collector(NevCollector),
        transform=records_to_nev_frame,
        target_file="nev_monthly_sales.parquet",
        primary_keys=["report_month"],
        raw_subdir=AUTOMOTIVE_RAW_SUBDIR,
        raw_target_file="data.parquet",
        raw_transform=records_to_raw_nev_frame,
        raw_primary_keys=["report_month"],
        require_context_coverage=True,
    ),
)
