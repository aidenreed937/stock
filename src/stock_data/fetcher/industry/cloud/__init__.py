"""北美四大云厂商季度 AI 资本开支 (10-Q) 数据工程子包。"""

from stock_data.fetcher.industry.cloud.collector import CloudCapexCollector
from stock_data.fetcher.industry.cloud.transform import (
    CLOUD_CAPEX_SCHEMA,
    empty_cloud_capex,
    records_to_cloud_capex_frame,
)

__all__ = [
    "CLOUD_CAPEX_SCHEMA",
    "CloudCapexCollector",
    "empty_cloud_capex",
    "records_to_cloud_capex_frame",
]
