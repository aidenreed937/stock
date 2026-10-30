"""航运产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.runner import collector, record_endpoint
from stock_data.fetcher.industry.shipping import ShippingCollector, records_to_shipping_frame

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    record_endpoint(
        endpoint="shipping_indices",
        domain="shipping",
        collect=collector(ShippingCollector),
        transform=records_to_shipping_frame,
        target_file="shipping_indices.parquet",
        primary_keys=["trade_date"],
    ),
)
