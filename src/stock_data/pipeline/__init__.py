"""ETL 处理、历史数据回填与增量同步编排引擎。"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock_data.pipeline.backfill import HistoricalBackfiller
    from stock_data.pipeline.backfill_runner import (
        BackfillRequest,
        run_backfill,
    )
    from stock_data.pipeline.index_member_versioned import (
        build_index_member_versioned,
        materialize_index_member_versioned,
    )
    from stock_data.pipeline.pipeline import MarketDataPipeline
    from stock_data.pipeline.planner import BackfillPlanner, BackfillTask
    from stock_data.pipeline.scheduler import DataUpdateScheduler
    from stock_data.pipeline.sw_industry_golden import (
        build_sw_2021_industry_dimension,
        build_sw_2021_industry_golden,
        build_sw_2021_industry_member_golden,
        load_sw_2021_industry_dimension,
        load_sw_2021_industry_symbols,
        materialize_sw_2021_industry_golden,
    )
    from stock_data.pipeline.sync import (
        DailySyncEngine,
        SyncExecutionResult,
        SyncTaskItem,
    )
    from stock_data.pipeline.sync_runner import SyncSourceRun, run_sync

__all__ = [
    "BackfillPlanner",
    "BackfillRequest",
    "BackfillTask",
    "DailySyncEngine",
    "DataUpdateScheduler",
    "HistoricalBackfiller",
    "MarketDataPipeline",
    "SyncExecutionResult",
    "SyncSourceRun",
    "SyncTaskItem",
    "build_index_member_versioned",
    "build_sw_2021_industry_dimension",
    "build_sw_2021_industry_golden",
    "build_sw_2021_industry_member_golden",
    "load_sw_2021_industry_dimension",
    "load_sw_2021_industry_symbols",
    "materialize_index_member_versioned",
    "materialize_sw_2021_industry_golden",
    "run_backfill",
    "run_sync",
]

_EXPORT_MAP: dict[str, tuple[str, str]] = {
    "HistoricalBackfiller": ("stock_data.pipeline.backfill", "HistoricalBackfiller"),
    "BackfillRequest": ("stock_data.pipeline.backfill_runner", "BackfillRequest"),
    "run_backfill": ("stock_data.pipeline.backfill_runner", "run_backfill"),
    "MarketDataPipeline": ("stock_data.pipeline.pipeline", "MarketDataPipeline"),
    "BackfillPlanner": ("stock_data.pipeline.planner", "BackfillPlanner"),
    "BackfillTask": ("stock_data.pipeline.planner", "BackfillTask"),
    "DataUpdateScheduler": ("stock_data.pipeline.scheduler", "DataUpdateScheduler"),
    "DailySyncEngine": ("stock_data.pipeline.sync", "DailySyncEngine"),
    "SyncExecutionResult": ("stock_data.pipeline.sync", "SyncExecutionResult"),
    "SyncTaskItem": ("stock_data.pipeline.sync", "SyncTaskItem"),
    "SyncSourceRun": ("stock_data.pipeline.sync_runner", "SyncSourceRun"),
    "run_sync": ("stock_data.pipeline.sync_runner", "run_sync"),
    "build_index_member_versioned": (
        "stock_data.pipeline.index_member_versioned",
        "build_index_member_versioned",
    ),
    "materialize_index_member_versioned": (
        "stock_data.pipeline.index_member_versioned",
        "materialize_index_member_versioned",
    ),
    "build_sw_2021_industry_dimension": (
        "stock_data.pipeline.sw_industry_golden",
        "build_sw_2021_industry_dimension",
    ),
    "build_sw_2021_industry_golden": (
        "stock_data.pipeline.sw_industry_golden",
        "build_sw_2021_industry_golden",
    ),
    "build_sw_2021_industry_member_golden": (
        "stock_data.pipeline.sw_industry_golden",
        "build_sw_2021_industry_member_golden",
    ),
    "materialize_sw_2021_industry_golden": (
        "stock_data.pipeline.sw_industry_golden",
        "materialize_sw_2021_industry_golden",
    ),
    "load_sw_2021_industry_symbols": (
        "stock_data.pipeline.sw_industry_golden",
        "load_sw_2021_industry_symbols",
    ),
    "load_sw_2021_industry_dimension": (
        "stock_data.pipeline.sw_industry_golden",
        "load_sw_2021_industry_dimension",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORT_MAP:
        mod_name, attr_name = _EXPORT_MAP[name]
        import importlib

        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
