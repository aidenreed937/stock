"""云计算产业端点注册。"""

from stock_data.fetcher.industry.cloud import (
    CloudCapexCollector,
    build_cloud_capex_curated_frame,
    build_cloud_capex_raw_frame,
)
from stock_data.fetcher.industry.contracts import IndustryEndpointSpec
from stock_data.fetcher.industry.runner import context_collector, frame_endpoint

ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    frame_endpoint(
        endpoint="cloud_capex_quarterly",
        domain="cloud",
        context_collect=context_collector(CloudCapexCollector, "collect_raw"),
        transform=build_cloud_capex_curated_frame,
        target_file="cloud_capex_quarterly.parquet",
        primary_keys=["report_quarter"],
        raw_subdir="cloud",
        raw_transform=build_cloud_capex_raw_frame,
    ),
)
