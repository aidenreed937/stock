"""垂直产业单端点采集执行器。"""

import logging
from datetime import date
from pathlib import Path

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.contracts import IndustryRunContext, IndustryRunResult
from stock_data.fetcher.industry.registry import get_endpoint_spec
from stock_data.fetcher.industry.runner import run_endpoint

logger = logging.getLogger(__name__)


def execute_single_industry_task(
    endpoint: str,
    start_date: date | None = None,
    end_date: date | None = None,
    force_refresh: bool = False,
    refresh_raw_cache: bool = False,
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
    runtime: DataRuntimeContext | None = None,
) -> IndustryRunResult:
    """执行单个垂直产业 Task 采集、清洗、增量合并与 Parquet 落盘。"""
    if runtime is not None:
        raw_path = runtime.raw_root / "industry"
        curated_path = runtime.curated_root / "industry"
    else:
        raw_path = Path(raw_dir)
        curated_path = Path(curated_dir)
    try:
        spec = get_endpoint_spec(endpoint)
    except KeyError:
        logger.warning("未知的垂直产业任务端点: %s", endpoint)
        return IndustryRunResult(0, status="UNKNOWN", errors=(f"未知端点: {endpoint}",))

    context = IndustryRunContext(
        endpoint=endpoint,
        raw_dir=raw_path,
        curated_dir=curated_path,
        start_date=start_date,
        end_date=end_date,
        force_refresh=force_refresh,
        refresh_raw_cache=refresh_raw_cache,
        runtime=runtime,
    )
    return run_endpoint(spec, context)
