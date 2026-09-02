"""垂直产业单端点采集执行器。"""

import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs import ComtradeCollector, records_to_customs_trade_frame
from stock_data.fetcher.industry.semiconductor_task_executor import backfill_semiconductor_china
from stock_data.fetcher.industry.silicon_task_executor import (
    SILICON_BRANCH_ENDPOINTS,
    execute_polysilicon_balance,
    execute_silicon_branch_derived,
    execute_silicon_wafer_monthly,
    execute_solar_supply_demand,
)
from stock_data.fetcher.industry.task_handlers import (
    SIMPLE_FRAME_HANDLERS,
    SIMPLE_RECORD_HANDLERS,
    FrameHandler,
    RecordHandler,
)

logger = logging.getLogger(__name__)


def execute_single_industry_task(
    endpoint: str,
    start_date: date | None = None,
    end_date: date | None = None,
    force_refresh: bool = False,
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
) -> int:
    """执行单个垂直产业 Task 采集、清洗、增量合并与 Parquet 落盘。"""
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    curated_path.mkdir(parents=True, exist_ok=True)

    record_handler = SIMPLE_RECORD_HANDLERS.get(endpoint)
    if record_handler is not None:
        count = _execute_record_handler(record_handler, raw_path, curated_path, force_refresh)
        if endpoint == "semiconductor_sales" and count:
            backfill_semiconductor_china(curated_path)
        return count

    frame_handler = SIMPLE_FRAME_HANDLERS.get(endpoint)
    if frame_handler is not None:
        return _execute_frame_handler(frame_handler, raw_path, curated_path, force_refresh)

    if endpoint == "customs_trade":
        return _execute_customs_trade(raw_path, curated_path, start_date, end_date)
    if endpoint == "silicon_wafer_monthly":
        return execute_silicon_wafer_monthly(raw_path, curated_path)
    if endpoint in SILICON_BRANCH_ENDPOINTS:
        return execute_silicon_branch_derived(endpoint, raw_path, curated_path)
    if endpoint == "polysilicon_balance":
        return execute_polysilicon_balance(raw_path, curated_path)
    if endpoint == "solar_supply_demand":
        return execute_solar_supply_demand(raw_path, curated_path, _execute_dependency)

    logger.warning("未知的垂直产业任务端点: %s", endpoint)
    return 0


def _execute_record_handler(
    handler: RecordHandler, raw_path: Path, curated_path: Path, force: bool
) -> int:
    collect, transform, filename, primary_keys = handler
    records = collect(raw_path, force)
    if not records:
        return 0
    return save_curated_fact(transform(records), curated_path / filename, primary_keys=primary_keys)


def _execute_frame_handler(
    handler: FrameHandler, raw_path: Path, curated_path: Path, force: bool
) -> int:
    collect, filename, primary_keys = handler
    df = collect(raw_path, force)
    if df.is_empty():
        return 0
    return save_curated_fact(df, curated_path / filename, primary_keys=primary_keys)


def _execute_customs_trade(
    raw_path: Path, curated_path: Path, start_date: date | None, end_date: date | None
) -> int:
    start_m = start_date.strftime("%Y-%m") if start_date else None
    end_m = end_date.strftime("%Y-%m") if end_date else None
    records = ComtradeCollector(raw_dir=raw_path / "customs" / "comtrade").collect(
        start_month=start_m, end_month=end_m
    )
    if not records:
        return 0
    return save_curated_fact(
        records_to_customs_trade_frame(records),
        curated_path / "customs_trade.parquet",
        primary_keys=["product_key", "hs_code", "report_month"],
    )


def _execute_dependency(endpoint: str, raw_path: Path, curated_path: Path) -> int:
    return execute_single_industry_task(endpoint, raw_dir=raw_path, curated_dir=curated_path)
