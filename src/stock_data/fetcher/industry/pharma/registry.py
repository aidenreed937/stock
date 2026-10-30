"""医药产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.pharma import PharmaBdCollector, records_to_pharma_bd_frame
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="pharma_license_out",
        domain="pharma",
        collect=collector(PharmaBdCollector),
        transform=records_to_pharma_bd_frame,
        target_file="pharma_license_out.parquet",
        primary_keys=["report_month"],
    ),
)
