"""消费电子产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.electronics import (
    ConsumerElectronicsCollector,
    records_to_consumer_electronics_frame,
)
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="consumer_electronics",
        domain="electronics",
        collect=collector(ConsumerElectronicsCollector),
        transform=records_to_consumer_electronics_frame,
        target_file="consumer_electronics.parquet",
        primary_keys=["report_quarter"],
    ),
)
