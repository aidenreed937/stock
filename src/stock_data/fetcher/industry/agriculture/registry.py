"""农业产业端点注册。"""

from stock_data.fetcher.industry.agriculture import (
    AgriculturePorkCollector,
    records_to_agriculture_pork_frame,
)
from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="agriculture_pork",
        domain="agriculture",
        collect=collector(AgriculturePorkCollector),
        transform=records_to_agriculture_pork_frame,
        target_file="agriculture_pork.parquet",
        primary_keys=["report_month"],
    ),
)
