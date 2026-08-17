"""统一增量数据更新与自动化调度引擎 (DailySyncEngine)。

提供基于水位自动嗅探 (Watermark Sniffing)、发布窗口保护 (Wave Routing)、
多端点并发拉取与自动对账审计的一站式增量更新服务。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from stock_core.config.loader import load_data_config
from stock_data.catalog import DataCatalog
from stock_data.core.factory import create_pipeline
from stock_data.core.task_registry import expand_task_targets, resolve_task
from stock_data.pipeline.planner import _filter_supported_symbols, _should_expand_single_sync
from stock_data.pipeline.scheduler import DataUpdateScheduler

logger = logging.getLogger(__name__)

_INDEX_ENDPOINTS = {
    "index_daily",
    "index_dailybasic",
    "index_weight",
    "global_index_daily",
    "index_daily_bar",
    "index_valuation",
    "index_fundamental",
}
_FUND_ENDPOINTS = {"fund_daily", "fund_adj", "fund_share", "etf_share_size"}
_YFINANCE_MACRO_SYMBOLS = ["^TNX", "^IRX", "DX-Y.NYB", "GC=F", "CL=F", "HG=F", "^VIX"]


@dataclass(frozen=True)
class SyncTaskItem:
    """单个端点增量同步任务项。"""

    data_source: str
    endpoint: str
    dataset: str
    start_date: date
    end_date: date
    watermark: date | None
    status: str
    is_ready: bool
    reason: str = ""
    symbol: str = ""


@dataclass
class SyncExecutionResult:
    """增量同步执行统计结果。"""

    data_source: str
    endpoint: str
    start_date: date
    end_date: date
    records: int
    duration_s: float
    status: str
    error: str | None = None
    symbol: str = ""


def _sniff_watermarks(
    catalog: DataCatalog, data_source: str, endpoints: list[str] | None = None
) -> dict[str, date | None]:
    targets = expand_task_targets(data_source, endpoints)
    watermarks: dict[str, date | None] = {}
    for ep in targets:
        try:
            task = resolve_task(data_source, ep)
            latest_dates = catalog.latest_trade_dates(dataset=task.dataset, n=1)
            watermarks[ep] = latest_dates[0] if latest_dates else None
        except Exception as e:
            logger.debug(f"探测端点 [{ep}] 水位异常: {e}")
            watermarks[ep] = None
    return watermarks


def _sync_symbols_for_task(data_source: str, endpoint: str) -> list[str]:
    task = resolve_task(data_source, endpoint)
    if task.fetch_mode != "per_symbol" or (
        task.is_single_sync and not _should_expand_single_sync(data_source, task.task_name)
    ):
        return [""]

    try:
        data_cfg = load_data_config()
        watchlist = getattr(data_cfg.watchlists, data_source, None)
    except Exception as exc:
        logger.warning(f"加载同步标的池失败 [{data_source}/{endpoint}]: {exc}")
        watchlist = None

    if data_source in {"yfinance", "alphavantage"} and task.dataset == "macro_indicators":
        return _YFINANCE_MACRO_SYMBOLS if data_source == "yfinance" else ["CNH=X"]
    if watchlist is None:
        return []
    if data_source == "fred":
        return list(getattr(watchlist, "macro_series", []) or [])
    if task.task_name in _FUND_ENDPOINTS or task.dataset in _FUND_ENDPOINTS:
        return list(getattr(watchlist, "funds", []) or [])
    if task.task_name in _INDEX_ENDPOINTS or task.dataset in _INDEX_ENDPOINTS:
        indices = list(getattr(watchlist, "indices", []) or [])
        return _filter_supported_symbols(indices, data_source, task.task_name, data_cfg)
    stocks = list(getattr(watchlist, "stocks", []) or [])
    if stocks:
        return stocks
    return list(getattr(watchlist, "all_symbols", []) or [])


def _symbol_watermark(
    catalog: DataCatalog, data_source: str, dataset: str, symbol: str
) -> date | None:
    if not symbol:
        latest_dates = catalog.latest_trade_dates(dataset=dataset, n=1)
        return latest_dates[0] if latest_dates else None
    try:
        df = catalog.load_dataset(dataset, symbols=[symbol])
    except Exception as exc:
        logger.debug(f"探测标的水位异常 [{data_source}/{dataset}/{symbol}]: {exc}")
        return None
    if df.is_empty() or "trade_date" not in df.columns:
        return None
    max_date = df.get_column("trade_date").max()
    if isinstance(max_date, date):
        return max_date
    if max_date is not None:
        try:
            return date.fromisoformat(str(max_date))
        except ValueError:
            return None
    return None


def _symbol_base_date(data_source: str, symbol: str, endpoint: str = "") -> date | None:
    if not symbol:
        return None
    try:
        data_cfg = load_data_config()
        watchlist = getattr(data_cfg.watchlists, data_source, None)
        get_base_date = getattr(watchlist, "get_base_date", None)
        if callable(get_base_date):
            asset_type = (
                "index"
                if endpoint in _INDEX_ENDPOINTS
                else "fund"
                if endpoint in _FUND_ENDPOINTS
                else "stock"
            )
            try:
                base_date = get_base_date(symbol, asset_type)
            except TypeError:
                base_date = get_base_date(symbol)
            return base_date if isinstance(base_date, date) else None
    except Exception:
        return None
    return None


def _resolve_sync_target_date(
    data_source: str,
    endpoint: str,
    target_date: date,
    target_date_is_explicit: bool,
) -> date | None:
    """为默认增量同步解析 T+1 端点实际应补的最近交易日。"""
    if target_date_is_explicit:
        return target_date

    meta = DataUpdateScheduler.get_endpoint_update_meta(data_source, endpoint)
    if not meta.delay_in_trading_days:
        return target_date

    return DataUpdateScheduler.get_latest_trading_date(
        target_date, data_source=data_source, strictly_before=True
    )


def _run_sync_task(task: SyncTaskItem, force_refresh: bool) -> SyncExecutionResult:
    t0 = time.perf_counter()
    try:
        pipeline = create_pipeline(data_source=task.data_source, endpoint=task.endpoint)
        df = pipeline.sync_daily_bars(
            symbol=task.symbol,
            start_date=task.start_date,
            end_date=task.end_date,
            use_raw_cache=not force_refresh,
            force_refresh=force_refresh,
        )
        dur = round(time.perf_counter() - t0, 2)
        row_count = len(df) if df is not None and not df.is_empty() else 0
        return SyncExecutionResult(
            data_source=task.data_source,
            endpoint=task.endpoint,
            start_date=task.start_date,
            end_date=task.end_date,
            records=row_count,
            duration_s=dur,
            status="SUCCESS" if row_count > 0 else "NO_DATA",
            symbol=task.symbol,
        )
    except Exception as e:
        dur = round(time.perf_counter() - t0, 2)
        label = f"{task.data_source}/{task.endpoint}"
        if task.symbol:
            label = f"{label}/{task.symbol}"
        logger.error(f"增量同步任务 [{label}] 异常: {e}")
        return SyncExecutionResult(
            data_source=task.data_source,
            endpoint=task.endpoint,
            start_date=task.start_date,
            end_date=task.end_date,
            records=0,
            duration_s=dur,
            status="FAILED",
            error=str(e),
            symbol=task.symbol,
        )


class DailySyncEngine:
    """增量数据同步与自愈引擎。"""

    def __init__(self, data_source: str = "tushare", max_workers: int = 4) -> None:
        self.data_source = data_source
        self.max_workers = max_workers
        self.catalog = DataCatalog(data_source=data_source)

    def sniff_watermarks(self, endpoints: list[str] | None = None) -> dict[str, date | None]:
        """逆序探测指定端点的最新落盘交易日水位 (Watermark)。"""
        return _sniff_watermarks(self.catalog, self.data_source, endpoints)

    def build_sync_plan(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        current_datetime: datetime | None = None,
        target_date_is_explicit: bool = True,
    ) -> list[SyncTaskItem]:
        """结合落盘水位与更新时间窗口，生成最小必要增量同步任务计划。"""
        t_target = target_date or date.today()
        targets = expand_task_targets(self.data_source, endpoints)
        watermarks = self.sniff_watermarks(targets)

        plan: list[SyncTaskItem] = []
        for ep in targets:
            task = resolve_task(self.data_source, ep)
            symbols = _sync_symbols_for_task(self.data_source, ep)
            if task.fetch_mode == "per_symbol" and not symbols:
                plan.append(
                    SyncTaskItem(
                        data_source=self.data_source,
                        endpoint=ep,
                        dataset=task.dataset,
                        start_date=t_target,
                        end_date=t_target,
                        watermark=None,
                        status="FAILED",
                        is_ready=False,
                        reason="per_symbol 任务缺少同步标的池",
                    )
                )
                continue

            sync_target = _resolve_sync_target_date(
                self.data_source, ep, t_target, target_date_is_explicit
            )
            if sync_target is None:
                for sym in symbols:
                    plan.append(
                        SyncTaskItem(
                            data_source=self.data_source,
                            endpoint=ep,
                            dataset=task.dataset,
                            start_date=t_target,
                            end_date=t_target,
                            watermark=_symbol_watermark(
                                self.catalog, self.data_source, task.dataset, sym
                            )
                            if sym
                            else watermarks.get(ep),
                            status="SKIPPED",
                            is_ready=False,
                            reason="交易日历不可用",
                            symbol=sym,
                        )
                    )
                continue

            ready = DataUpdateScheduler.is_data_ready(
                endpoint=ep,
                target_date=sync_target,
                current_datetime=current_datetime,
                data_source=self.data_source,
            )

            if not ready and not force:
                meta = DataUpdateScheduler.get_endpoint_update_meta(self.data_source, ep)
                for sym in symbols:
                    plan.append(
                        SyncTaskItem(
                            data_source=self.data_source,
                            endpoint=ep,
                            dataset=task.dataset,
                            start_date=sync_target,
                            end_date=sync_target,
                            watermark=_symbol_watermark(
                                self.catalog, self.data_source, task.dataset, sym
                            )
                            if sym
                            else watermarks.get(ep),
                            status="SKIPPED",
                            is_ready=False,
                            reason=f"窗口未到 ({meta.update_time} T+{meta.update_delay_days})",
                            symbol=sym,
                        )
                    )
                continue

            for sym in symbols:
                w_date = (
                    _symbol_watermark(self.catalog, self.data_source, task.dataset, sym)
                    if sym
                    else watermarks.get(ep)
                )
                if not force and w_date is not None and w_date >= sync_target:
                    plan.append(
                        SyncTaskItem(
                            data_source=self.data_source,
                            endpoint=ep,
                            dataset=task.dataset,
                            start_date=sync_target,
                            end_date=sync_target,
                            watermark=w_date,
                            status="UP_TO_DATE",
                            is_ready=True,
                            reason="已是最新",
                            symbol=sym,
                        )
                    )
                    continue

                # 推导待补齐起始日期（自愈缺口）
                if w_date is not None:
                    start_d = w_date + timedelta(days=1)
                    # 若水位已经是当天或更晚，且处于 force 模式，覆盖更新当天
                    start_d = min(start_d, sync_target)
                else:
                    base_date = _symbol_base_date(self.data_source, sym, ep)
                    start_d = base_date if base_date and base_date <= sync_target else sync_target

                plan.append(
                    SyncTaskItem(
                        data_source=self.data_source,
                        endpoint=ep,
                        dataset=task.dataset,
                        start_date=start_d,
                        end_date=sync_target,
                        watermark=w_date,
                        status="PENDING",
                        is_ready=True,
                        reason=f"待增量 ({start_d} ~ {sync_target})",
                        symbol=sym,
                    )
                )
        return plan

    def execute_plan(
        self, plan: list[SyncTaskItem], force_refresh: bool = False
    ) -> list[SyncExecutionResult]:
        """并发执行增量同步任务。"""
        pending = [t for t in plan if t.status == "PENDING"]
        if not pending:
            return []

        results: list[SyncExecutionResult] = []

        workers = min(self.max_workers, len(pending))
        if workers <= 1:
            for task in pending:
                results.append(_run_sync_task(task, force_refresh))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run_sync_task, task, force_refresh) for task in pending]
                for fut in as_completed(futures):
                    results.append(fut.result())

        return results

    def sync_daily(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        run_audit_gate: bool = True,
        target_date_is_explicit: bool = True,
    ) -> tuple[list[SyncTaskItem], list[SyncExecutionResult], dict[str, Any] | None]:
        """一站式完成增量计划生成、执行与质量对账。"""
        t_target = target_date or date.today()
        plan = self.build_sync_plan(
            target_date=t_target,
            endpoints=endpoints,
            force=force,
            target_date_is_explicit=target_date_is_explicit,
        )
        exec_results = self.execute_plan(plan, force_refresh=force)

        audit_result: dict[str, Any] | None = None
        if run_audit_gate and any(r.status == "SUCCESS" for r in exec_results):
            try:
                from stock_data.governance.audit.reconciliation import run_audit

                logger.info(f"增量同步完成，正在触发 [{t_target}] 质量对账门禁...")
                audit_date = next(
                    (
                        result.end_date
                        for result in exec_results
                        if result.endpoint == "stock_daily_bar" and result.status == "SUCCESS"
                    ),
                    t_target,
                )
                audit_result = run_audit(
                    target_date=audit_date, data_source=self.data_source, quiet=True
                )
            except Exception as e:
                logger.warning(f"增量后自动审计异常: {e}")

        return plan, exec_results, audit_result
