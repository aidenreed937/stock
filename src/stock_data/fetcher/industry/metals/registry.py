"""有色金属产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.metals import NonFerrousCollector, records_to_metals_frame
from stock_data.fetcher.industry.runner import collector, record_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="non_ferrous_metals",
        domain="metals",
        collect=collector(NonFerrousCollector),
        transform=records_to_metals_frame,
        target_file="non_ferrous_metals.parquet",
        primary_keys=["trade_date"],
    ),
)
