"""海关贸易产业端点注册。"""

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec, IndustryRunContext
from stock_data.fetcher.industry.curated_store import save_curated_dataset
from stock_data.fetcher.industry.customs.collectors import (
    ComtradeCollector,
    GaccCollector,
)
from stock_data.fetcher.industry.customs.paths import CustomsRawPaths
from stock_data.fetcher.industry.customs.transforms import (
    records_to_customs_trade_frame,
)
from stock_data.fetcher.industry.runner import collector, record_endpoint


def _run_customs_trade(context: IndustryRunContext) -> int:
    start_month = context.start_date.strftime("%Y-%m") if context.start_date else None
    end_month = context.end_date.strftime("%Y-%m") if context.end_date else None
    records = ComtradeCollector(raw_dir=CustomsRawPaths(context.raw_dir).comtrade_dir).collect(
        start_month=start_month,
        end_month=end_month,
    )
    if not records:
        return 0
    return save_curated_dataset(
        records_to_customs_trade_frame(records),
        context.curated_dir / "customs_trade.parquet",
        primary_keys=["product_key", "hs_code", "report_month", "trade_direction"],
    )


ENDPOINT_SPECS: tuple[IndustryEndpointSpec, ...] = (
    IndustryEndpointSpec(endpoint="customs_trade", domain="customs", run=_run_customs_trade),
    record_endpoint(
        endpoint="gacc_trade",
        domain="customs",
        collect=collector(GaccCollector),
        transform=records_to_customs_trade_frame,
        target_file="customs_trade_gacc.parquet",
        primary_keys=[
            "product_key",
            "hs_code",
            "report_month",
            "trade_direction",
            "trade_value_currency",
        ],
        require_context_coverage=True,
        context_coverage_frequency="monthly",
    ),
)
