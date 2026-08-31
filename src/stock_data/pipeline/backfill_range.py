"""历史回填执行策略与模式分发辅助模块。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from stock_core.utils.logger import logger
from stock_data.core.task_registry import is_per_symbol_task, resolve_public_task

if TYPE_CHECKING:
    from stock_data.pipeline.backfill import HistoricalBackfiller


def _backfill_industry_metric(endpoint: str, total_days: int) -> dict[str, Any]:
    """执行中观产业指标回填。"""
    from stock_data.fetcher.industry.pipeline import sync_all_industry_metrics

    try:
        res_dict = sync_all_industry_metrics(metrics=[endpoint])
        count = res_dict.get(endpoint, 0)
        return {
            "total_days": total_days,
            "open_days": 1,
            "synced_days": count,
            "skipped_days": 0 if count > 0 else 1,
            "failed_days": 0,
        }
    except Exception as err:
        logger.error(f"中观产业指标 [{endpoint}] 回填异常: {err}")
        return {
            "total_days": total_days,
            "open_days": 1,
            "synced_days": 0,
            "skipped_days": 0,
            "failed_days": 1,
        }


def _backfill_range_mode(
    backfiller: HistoricalBackfiller,
    start_date: date,
    end_date: date,
    force_refresh: bool,
    max_workers: int,
    total_days: int,
) -> dict[str, Any]:
    """执行范围拉取模式回填 (月频/宏观/静态/按标的历史范围)。"""
    from stock_data.pipeline.backfill import _sync_pipeline

    task_spec = resolve_public_task(backfiller.data_source, backfiller.endpoint)
    is_per_sym = is_per_symbol_task(backfiller.data_source, backfiller.endpoint)
    sym_code = (
        ""
        if task_spec.fetch_mode == "per_period"
        else backfiller.symbol or ("" if is_per_sym else backfiller.endpoint)
    )
    is_short_daily_symbol_range = (
        not force_refresh
        and backfiller.symbol
        and backfiller.frequency == "daily"
        and (end_date - start_date).days <= 30
    )
    if is_short_daily_symbol_range:
        open_dates = backfiller._get_open_trading_dates(start_date, end_date, use_cache=True)
        todo_dates = backfiller._generate_tasks(start_date, end_date, force_refresh=False)
        if not todo_dates:
            return {
                "total_days": total_days,
                "open_days": len(open_dates),
                "synced_days": 0,
                "skipped_days": len(open_dates),
                "failed_days": 0,
            }

    try:
        df = _sync_pipeline(
            backfiller.pipeline, sym_code, start_date, end_date, force_refresh, max_workers
        )
        count = len(df) if not df.is_empty() else 0
        return {
            "total_days": total_days,
            "open_days": 1,
            "synced_days": count,
            "skipped_days": 1 if count == 0 else 0,
            "failed_days": 0,
        }
    except Exception as err:
        logger.error(f"标的 [{sym_code}] 范围回填异常: {err}")
        return {
            "total_days": total_days,
            "open_days": 1,
            "synced_days": 0,
            "skipped_days": 0,
            "failed_days": 1,
        }


def _backfill_daily_slices_mode(
    backfiller: HistoricalBackfiller,
    start_date: date,
    end_date: date,
    force_refresh: bool,
    max_workers: int,
    total_days: int,
) -> dict[str, Any]:
    """执行按交易日切片并行拉取模式 (全市场每日截面)。"""
    from stock_data.pipeline.backfill import _execute_parallel_tasks, _sync_pipeline

    open_dates = backfiller._get_open_trading_dates(
        start_date, end_date, use_cache=not force_refresh
    )
    todo_dates = backfiller._generate_tasks(start_date, end_date, force_refresh=force_refresh)
    skipped_count = len(open_dates) - len(todo_dates)

    if not todo_dates:
        return {
            "total_days": total_days,
            "open_days": len(open_dates),
            "synced_days": 0,
            "skipped_days": skipped_count,
            "failed_days": 0,
        }

    def _sync_day(d: date) -> bool:
        try:
            df = _sync_pipeline(
                backfiller.pipeline, backfiller.symbol or "", d, d, force_refresh, max_workers
            )
            if backfiller.endpoint in (
                "report_rc",
                "forecast",
                "express",
                "margin_detail",
                "hsgt_top10",
            ):
                return True
            return not df.is_empty()
        except Exception as e:
            logger.error(f"交易日 [{d}] 同步异常: {e}")
            return False

    synced_count, failed_count = _execute_parallel_tasks(
        task_fn=_sync_day,
        items=todo_dates,
        max_workers=max_workers,
        item_desc=lambda d: f"交易日 [{d}] 数据",
    )

    return {
        "total_days": total_days,
        "open_days": len(open_dates),
        "synced_days": synced_count,
        "skipped_days": skipped_count,
        "failed_days": failed_count,
    }


def execute_backfill_range(
    backfiller: HistoricalBackfiller,
    start_date: date,
    end_date: date,
    force_refresh: bool = False,
    max_workers: int = 1,
) -> dict[str, Any]:
    """路由并执行指定范围的数据回填。"""
    total_days = (end_date - start_date).days + 1
    if backfiller.data_source == "industry":
        return _backfill_industry_metric(backfiller.endpoint, total_days)

    freq = backfiller.frequency
    task_spec = resolve_public_task(backfiller.data_source, backfiller.endpoint)
    is_per_sym = is_per_symbol_task(backfiller.data_source, backfiller.endpoint)

    if freq != "daily" or is_per_sym or task_spec.is_single_sync:
        return _backfill_range_mode(
            backfiller, start_date, end_date, force_refresh, max_workers, total_days
        )

    return _backfill_daily_slices_mode(
        backfiller, start_date, end_date, force_refresh, max_workers, total_days
    )
