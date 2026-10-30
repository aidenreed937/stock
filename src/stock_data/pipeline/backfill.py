"""全市场历史数据回填调度器 (HistoricalBackfiller)。

支持按自定义历史日期范围（如过去 5 年、10 年）进行交易日历自动对齐、断点续传与两层 ETL 数据回填。
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from stock_core.exceptions import DataFetchError
from stock_core.utils.logger import logger
from stock_data.core.factory import create_pipeline
from stock_data.core.public_tasks import resolve_public_task
from stock_data.fetcher.base import BaseDataFetcher
from stock_data.pipeline.pipeline import MarketDataPipeline
from stock_data.pipeline.planner import (
    _default_symbols_for_endpoint,
    _filter_supported_symbols,
    _watchlist_symbols,
)
from stock_data.pipeline.planner import (
    _load_curated_symbol_pool as _load_curated_symbol_pool,
)
from stock_data.pipeline.scheduler import DataUpdateScheduler


def _failed_item_count(item: Any) -> int:
    if isinstance(item, date):
        return 1
    if isinstance(item, tuple):
        return len(item[1])
    return 1


def _sync_pipeline(
    pipeline: Any,
    symbol: str,
    start_date: date,
    end_date: date,
    force_refresh: bool,
    max_workers: int,
) -> Any:
    """调用 Pipeline，并仅在需要时向 Fetcher 传递并发参数。"""
    kwargs: dict[str, Any] = {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "use_raw_cache": not force_refresh,
        "force_refresh": force_refresh,
    }
    if max_workers > 1:
        kwargs["max_workers"] = max_workers
    return pipeline.sync_daily_bars(**kwargs)


def _resolve_calendar_dates(
    fetcher: BaseDataFetcher | None,
    data_source: str,
    start_date: date,
    end_date: date,
    endpoint: str = "",
) -> list[date]:
    """获取开市有效交易日列表，缺少可信交易日历时 fail-closed。"""
    if data_source.lower() in {"fred", "industry"}:
        return [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

    if data_source.lower() == "tushare" and endpoint == "us_stock_daily_bar":
        import exchange_calendars as xcals

        sessions = xcals.get_calendar("XNYS").sessions_in_range(
            start_date.isoformat(), end_date.isoformat()
        )
        return [session.date() for session in sessions]

    if data_source.lower() in {"tushare", "lixinger"}:
        try:
            local_calendar = DataUpdateScheduler.get_trading_days(
                start_date, end_date, data_source="tushare"
            )
            if local_calendar:
                return list(local_calendar)
        except Exception as err:
            logger.warning(
                f"[{data_source}] 本地 TuShare trade_cal 读取失败，将尝试源端日历: {err}"
            )

    fetch_trade_cal_fn = getattr(fetcher, "fetch_trade_cal", None)
    if callable(fetch_trade_cal_fn):
        try:
            res = fetch_trade_cal_fn(start_date, end_date)
            if isinstance(res, list):
                dates = [d for d in res if isinstance(d, date)]
                if dates:
                    return dates
        except Exception as err:
            logger.warning(f"[{data_source}] 源端交易日历获取失败，无法建立可信日历: {err}")

    raise DataFetchError(
        f"[{data_source}] 缺少 {start_date} ~ {end_date} 的可信交易日历，拒绝按工作日推算。"
    )


def _execute_parallel_tasks(
    task_fn: Callable[[Any], bool | int],
    items: list[Any],
    max_workers: int,
    item_desc: Callable[[Any], str],
) -> tuple[int, int]:
    """多线程并发执行任务并统计成功与失败数。"""
    synced = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(task_fn, item): item for item in items}
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                res = future.result()
                if res is True or (isinstance(res, int) and res > 0):
                    synced += 1
                else:
                    failed += _failed_item_count(item)
            except Exception as err:
                logger.error(f"任务 [{item_desc(item)}] 并发执行异常: {err}")
                failed += _failed_item_count(item)
    return synced, failed


class HistoricalBackfiller:
    """生产级历史数据回填调度引擎。"""

    def __init__(
        self,
        pipeline: MarketDataPipeline | None = None,
        fetcher: BaseDataFetcher | None = None,
        data_source: str = "tushare",
        endpoint: str = "stock_daily_bar",
        symbol: str = "",
    ) -> None:
        self.symbol = symbol
        self.data_source = data_source
        self.endpoint = resolve_public_task(data_source, endpoint).task_name
        self._calendar_cache: dict[tuple[date, date], list[date]] = {}
        self.pipeline: MarketDataPipeline | None = None
        self.fetcher: BaseDataFetcher | None = None

        if self.data_source == "industry":
            self.pipeline = None
            self.fetcher = None
        elif pipeline is not None:
            self.pipeline = pipeline
            self.fetcher = fetcher or pipeline.fetcher
        else:
            self.pipeline = create_pipeline(
                data_source=data_source, endpoint=self.endpoint, fetcher=fetcher
            )
            self.fetcher = self.pipeline.fetcher

    @property
    def frequency(self) -> str:
        """自动在注册表中识别当前任务频次。"""
        registry_map = {
            "tushare": "stock_data.fetcher.tushare.registry",
            "lixinger": "stock_data.fetcher.lixinger.registry",
            "yfinance": "stock_data.fetcher.yfinance.registry",
            "fred": "stock_data.fetcher.fred.registry",
        }
        mod_path = registry_map.get(self.data_source)
        if mod_path:
            import importlib

            try:
                mod = importlib.import_module(mod_path)
                reg_dict = (
                    getattr(mod, "TUSHARE_API_REGISTRY", None)
                    or getattr(mod, "LIXINGER_API_REGISTRY", None)
                    or getattr(mod, "YFINANCE_API_REGISTRY", None)
                    or getattr(mod, "FRED_API_REGISTRY", None)
                )
                task = resolve_public_task(self.data_source, self.endpoint)
                if reg_dict and task.api_name in reg_dict:
                    return getattr(reg_dict[task.api_name], "frequency", task.frequency)
            except Exception:
                pass
        return "daily"

    def _get_open_trading_dates(
        self, start_date: date, end_date: date, use_cache: bool = True
    ) -> list[date]:
        cache_key = (start_date, end_date)
        if use_cache and cache_key in self._calendar_cache:
            return self._calendar_cache[cache_key]

        dates = _resolve_calendar_dates(
            self.fetcher,
            self.data_source,
            start_date,
            end_date,
            endpoint=self.endpoint,
        )
        self._calendar_cache[cache_key] = dates
        return dates

    def _generate_tasks(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> list[date]:
        open_dates = self._get_open_trading_dates(start_date, end_date, use_cache=not force_refresh)
        if force_refresh:
            return open_dates

        todo_dates = []
        for trade_date in open_dates:
            has_curated = (
                getattr(self.pipeline.store, "has_curated", lambda e, d, s=None: False)(
                    self.endpoint, trade_date, self.symbol
                )
                if self.pipeline is not None
                else False
            )
            has_raw = True
            raw_store = (
                getattr(self.pipeline, "raw_store", None) if self.pipeline is not None else None
            )
            if not force_refresh and raw_store is not None and hasattr(raw_store, "has_raw"):
                has_raw = bool(
                    raw_store.has_raw(self.data_source, self.endpoint, trade_date, self.symbol)
                )
            if has_curated and has_raw and not force_refresh:
                continue

            if not DataUpdateScheduler.is_data_ready(
                endpoint=self.endpoint, target_date=trade_date, data_source=self.data_source
            ):
                continue
            todo_dates.append(trade_date)
        return todo_dates

    def backfill_range(
        self,
        start_date: date,
        end_date: date,
        force_refresh: bool = False,
        max_workers: int = 1,
    ) -> dict[str, Any]:
        """按交易日范围进行历史数据批量回填。"""
        from stock_data.pipeline.backfill_range import execute_backfill_range

        return execute_backfill_range(
            self,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
            max_workers=max_workers,
        )


def _load_backfill_yaml_config(
    config_path_str: str = "config/data.yaml",
) -> dict[str, Any]:
    """加载 YAML 回填配置文件。"""
    from pathlib import Path

    import yaml

    config_path = Path(config_path_str)
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f)
                if cfg_data:
                    if "data" in cfg_data and isinstance(cfg_data["data"], dict):
                        b_cfg = cfg_data["data"].get("backfill")
                        if isinstance(b_cfg, dict):
                            return b_cfg
                    if "backfill" in cfg_data and isinstance(cfg_data["backfill"], dict):
                        return cfg_data["backfill"]
        except Exception as e:
            logger.warning(f"加载回填配置文件 [{config_path_str}] 失败: {e}")
    return {}


__all__ = [
    "HistoricalBackfiller",
    "_default_symbols_for_endpoint",
    "_execute_parallel_tasks",
    "_filter_supported_symbols",
    "_load_backfill_yaml_config",
    "_resolve_calendar_dates",
    "_watchlist_symbols",
    "resolve_public_task",
]
