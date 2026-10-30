"""增量同步计划生成器。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from stock_data.catalog import DataCatalog
from stock_data.core.task_resolution import expand_task_targets, resolve_task
from stock_data.pipeline.report_probe import (
    YFINANCE_FINANCIAL_PROBE_EPOCH,
    ReportProbeDecision,
)
from stock_data.pipeline.scheduler import DataUpdateScheduler
from stock_data.pipeline.sync_models import SyncTaskItem
from stock_data.pipeline.sync_target import normalize_watermark_date

REFRESH_WATERMARK_FREQUENCIES = {"static", "event"}


def build_sync_plan(
    catalog: DataCatalog,
    data_source: str,
    target_date: date | None,
    endpoints: list[str] | None,
    force: bool,
    current_datetime: datetime | None,
    target_date_is_explicit: bool,
    sniff_watermarks: Callable[..., dict[str, date | None]],
    disabled_endpoints: Callable[[str], set[str]],
    sync_symbols_for_task: Callable[[str, str], list[str]],
    symbol_watermarks: Callable[..., dict[str, date | None]],
    symbol_refresh_watermarks: Callable[..., dict[str, date | None]],
    schedule_endpoint: Callable[[str, str, str], str],
    next_increment_start: Callable[[date, str, str, str], date],
    symbol_base_date: Callable[[str, str, str], date | None],
    expand_task_targets_fn: Callable[..., list[str]] = expand_task_targets,
    resolve_task_fn: Callable[..., Any] = resolve_task,
    report_probe_decision: Callable[..., ReportProbeDecision] | None = None,
) -> list[SyncTaskItem]:
    """结合落盘水位与更新时间窗口，生成最小必要增量同步任务计划。"""
    target = target_date or date.today()
    targets = expand_task_targets_fn(data_source, endpoints)
    watermarks = sniff_watermarks(targets)
    disabled = disabled_endpoints(data_source)
    endpoint_tasks: dict[str, Any] = {}
    endpoint_symbols: dict[str, list[str]] = {}
    symbols_by_dataset: dict[str, set[str]] = {}
    refresh_datasets: set[str] = set()
    for endpoint in targets:
        task = resolve_task_fn(data_source, endpoint)
        endpoint_tasks[endpoint] = task
        if endpoint in disabled:
            continue
        symbols = sync_symbols_for_task(data_source, endpoint)
        endpoint_symbols[endpoint] = symbols
        if task.fetch_mode == "per_symbol":
            symbols_by_dataset.setdefault(task.dataset, set()).update(
                symbol for symbol in symbols if symbol
            )
            frequency = DataUpdateScheduler.get_endpoint_update_meta(
                data_source, endpoint
            ).frequency
            if frequency in REFRESH_WATERMARK_FREQUENCIES:
                refresh_datasets.add(task.dataset)

    symbol_watermarks_by_dataset = {
        dataset: (
            symbol_refresh_watermarks(catalog, data_source, dataset, sorted(symbols))
            if dataset in refresh_datasets
            else symbol_watermarks(catalog, data_source, dataset, sorted(symbols))
        )
        for dataset, symbols in symbols_by_dataset.items()
        if symbols
    }

    plan: list[SyncTaskItem] = []
    for endpoint in targets:
        task = endpoint_tasks[endpoint]
        if endpoint in disabled:
            plan.append(
                SyncTaskItem(
                    data_source=data_source,
                    endpoint=endpoint,
                    dataset=task.dataset,
                    start_date=target,
                    end_date=target,
                    watermark=None,
                    status="SKIPPED",
                    is_ready=False,
                    reason="配置为不可用任务（账户权限或额度不足）",
                )
            )
            continue

        symbols = endpoint_symbols[endpoint]
        if task.fetch_mode == "per_symbol" and not symbols:
            plan.append(
                SyncTaskItem(
                    data_source=data_source,
                    endpoint=endpoint,
                    dataset=task.dataset,
                    start_date=target,
                    end_date=target,
                    watermark=None,
                    status="FAILED",
                    is_ready=False,
                    reason="per_symbol 任务缺少同步标的池",
                )
            )
            continue

        for symbol in symbols:
            scheduled_endpoint = schedule_endpoint(data_source, endpoint, symbol)
            is_period_task = task.fetch_mode == "per_period" or task.query_mode == "period"
            is_yfinance_report_probe = data_source == "yfinance" and task.query_mode == "period"
            sync_target = _resolve_sync_target_date(
                data_source,
                scheduled_endpoint,
                target,
                target_date_is_explicit,
                current_datetime,
            )
            watermark = (
                symbol_watermarks_by_dataset.get(task.dataset, {}).get(symbol)
                if symbol
                else watermarks.get(endpoint)
            )
            frequency = DataUpdateScheduler.get_endpoint_update_meta(
                data_source, scheduled_endpoint
            ).frequency
            period_watermark = (
                watermark
                if is_period_task
                else normalize_watermark_date(watermark, frequency)
                if watermark is not None
                else None
            )
            if is_yfinance_report_probe:
                sync_target = period_watermark or YFINANCE_FINANCIAL_PROBE_EPOCH
            if sync_target is None:
                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=target,
                        end_date=target,
                        watermark=watermark,
                        status="SKIPPED",
                        is_ready=False,
                        reason="交易日历不可用",
                        symbol=symbol,
                    )
                )
                continue

            if (
                not force
                and getattr(task, "sync_policy", "incremental") == "manual_snapshot"
                and watermark is not None
            ):
                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=sync_target,
                        end_date=sync_target,
                        watermark=watermark,
                        status="UP_TO_DATE",
                        is_ready=True,
                        reason="手工存证任务已有发布日期水位；新增或修订请显式 FORCE=1",
                        symbol=symbol,
                    )
                )
                continue

            ready = DataUpdateScheduler.is_data_ready(
                endpoint=scheduled_endpoint,
                target_date=sync_target,
                current_datetime=current_datetime,
                data_source=data_source,
            )
            if not ready and not force:
                meta = DataUpdateScheduler.get_endpoint_update_meta(data_source, scheduled_endpoint)
                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=sync_target,
                        end_date=sync_target,
                        watermark=watermark,
                        status="SKIPPED",
                        is_ready=False,
                        reason=(
                            f"窗口未到 ({meta.update_time} T+"
                            f"{DataUpdateScheduler.effective_update_delay_days(meta, sync_target)})"
                        ),
                        symbol=symbol,
                    )
                )
                continue
            current_period_refresh = (
                task.fetch_mode == "per_period"
                and getattr(task, "refresh_current_period", True)
                and period_watermark is not None
                and period_watermark == sync_target
            )
            sync_lookback_days = getattr(task, "sync_lookback_days", None)
            if sync_lookback_days is not None:
                rolling_start = sync_target - timedelta(days=max(int(sync_lookback_days), 0))
                lookback_start = (
                    sync_target
                    if period_watermark is None
                    else max(rolling_start, period_watermark)
                )
                lookback_start = min(lookback_start, sync_target)
                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=lookback_start,
                        end_date=sync_target,
                        watermark=watermark,
                        status="PENDING",
                        is_ready=True,
                        reason=f"事件滚动回看 ({lookback_start} ~ {sync_target})",
                        symbol=symbol,
                        refresh_raw_cache=True,
                    )
                )
                continue
            if (
                not force
                and not is_yfinance_report_probe
                and period_watermark is not None
                and period_watermark >= sync_target
                and not current_period_refresh
            ):
                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=sync_target,
                        end_date=sync_target,
                        watermark=watermark,
                        status="UP_TO_DATE",
                        is_ready=True,
                        reason="已是最新",
                        symbol=symbol,
                    )
                )
                continue

            if is_yfinance_report_probe:
                if not force and report_probe_decision is not None:
                    decision = report_probe_decision(
                        endpoint,
                        symbol,
                        sync_target,
                        current_datetime,
                    )
                    if not decision.due:
                        next_probe = (
                            decision.next_probe_at.isoformat()
                            if decision.next_probe_at is not None
                            else "稍后"
                        )
                        plan.append(
                            SyncTaskItem(
                                data_source=data_source,
                                endpoint=endpoint,
                                dataset=task.dataset,
                                start_date=sync_target,
                                end_date=sync_target,
                                watermark=watermark,
                                status="SKIPPED",
                                is_ready=True,
                                reason=f"财报基准期 {sync_target} 已检查，冷却至 {next_probe}",
                                symbol=symbol,
                            )
                        )
                        continue

                plan.append(
                    SyncTaskItem(
                        data_source=data_source,
                        endpoint=endpoint,
                        dataset=task.dataset,
                        start_date=sync_target,
                        end_date=sync_target,
                        watermark=watermark,
                        status="PENDING",
                        is_ready=True,
                        reason=(
                            f"首次探测财报 ({sync_target})"
                            if watermark is None
                            else f"周期性探测财报 ({sync_target})"
                        ),
                        symbol=symbol,
                        refresh_raw_cache=True,
                    )
                )
                continue

            if period_watermark is not None:
                if is_period_task and period_watermark >= sync_target:
                    start = sync_target
                else:
                    start = (
                        sync_target
                        if frequency in REFRESH_WATERMARK_FREQUENCIES
                        else next_increment_start(
                            period_watermark, data_source, scheduled_endpoint, frequency
                        )
                    )
                start = min(start, sync_target)
            else:
                base_date = symbol_base_date(data_source, symbol, endpoint)
                start = base_date if base_date and base_date <= sync_target else sync_target
            max_increment_days = getattr(task, "max_increment_days", None)
            if max_increment_days is not None and start < sync_target:
                start = max(start, sync_target - timedelta(days=max(int(max_increment_days), 0)))
            plan.append(
                SyncTaskItem(
                    data_source=data_source,
                    endpoint=endpoint,
                    dataset=task.dataset,
                    start_date=start,
                    end_date=sync_target,
                    watermark=watermark,
                    status="PENDING",
                    is_ready=True,
                    reason=(
                        f"待刷新报告期 ({start} ~ {sync_target})"
                        if current_period_refresh
                        else f"待增量 ({start} ~ {sync_target})"
                    ),
                    symbol=symbol,
                    refresh_raw_cache=current_period_refresh,
                )
            )
    return plan


def _resolve_sync_target_date(
    data_source: str,
    endpoint: str,
    target: date,
    target_date_is_explicit: bool,
    current_datetime: datetime | None,
) -> date | None:
    from stock_data.pipeline.sync_target import resolve_sync_target_date

    return resolve_sync_target_date(
        data_source, endpoint, target, target_date_is_explicit, current_datetime
    )
