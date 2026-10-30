"""工程机械产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.machinery import MachineryCollector, records_to_machinery_frame
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="construction_machinery",
        domain="machinery",
        collect=collector(MachineryCollector),
        transform=records_to_machinery_frame,
        target_file="construction_machinery.parquet",
        primary_keys=["report_month"],
        require_context_coverage=True,
    ),
)
