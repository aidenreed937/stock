"""全市场历史数据回填调度器 (HistoricalBackfiller)。

支持按自定义历史日期范围（如过去 5 年、10 年）进行交易日历自动对齐、断点续传与两层 ETL 数据回填。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Callable

from stock.data.factory import create_pipeline
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import is_per_symbol_task, resolve_public_task, resolve_task
from stock.data.update_scheduler import DataUpdateScheduler
from stock.exceptions import DataFetchError
from stock.utils.logger import logger

MARKET_SINGLE_SYNC_ENDPOINTS: set[str] = {
    # 宏观经济数据
    "moneyflow_hsgt",
    "hsgt_top10",
    "margin",
    "suspend_d",
    "cn_gdp",
    "cn_cpi",
    "cn_ppi",
    "cn_pmi",
    "cn_m",
    "sf_month",
    "shibor_lpr",
    # 静态/元数据/事件型接口 (只需 1 次全量获取)
    "stock_basic",
    "index_basic",
    "index_classify",
    "index_member",
    "fund_basic",
    "sw_2021_constituents",
    "sw_2021_fundamental",
    "company_fundamental",
    "index_fundamental",
    "fs_non_financial",
    "pledge_info",
}

TUSHARE_STOCK_POOL_ENDPOINTS = frozenset(
    {"income", "fina_indicator", "margin_detail", "hk_hold"}
)
TUSHARE_FUND_POOL_ENDPOINTS = frozenset({"fund_share"})


def _load_curated_symbol_pool(data_source: str, dataset: str) -> list[str]:
    """从本地基础信息数据集加载可用于按标的回填的标准代码。"""
    from stock.data.storage.duckdb_store import DuckDBMarketStore

    frame = DuckDBMarketStore(data_source=data_source).query_dataset(dataset=dataset)
    if frame.is_empty():
        return []
    sym_col = next((c for c in ("symbol", "ts_code", "stockCode", "code") if c in frame.columns), None)
    if not sym_col:
        return []
    vals = frame.get_column(sym_col).drop_nulls().to_list()
    return sorted({str(s).strip() for s in vals if str(s).strip()})


def _tushare_local_pool(endpoint: str) -> tuple[str, str] | None:
    """返回 TuShare 接口所需本地基础池及其缺失提示。"""
    if endpoint in TUSHARE_STOCK_POOL_ENDPOINTS:
        return "stock_basic", "A 股"
    if endpoint in TUSHARE_FUND_POOL_ENDPOINTS:
        return "fund_basic", "基金"
    return None


def _watchlist_symbols(
    data_source: str,
    endpoint: str,
    data_cfg: Any,
    per_symbol_endpoints: set[str],
) -> list[str]:
    """从配置观察池解析接口的默认标的。"""
    watchlist = getattr(data_cfg.watchlists, data_source, None)
    if watchlist is None:
        return []
    if endpoint in {"fund_daily", "fund_adj", "fund_share", "etf_share_size"} and getattr(watchlist, "funds", None):
        return list(watchlist.funds)
    if endpoint in per_symbol_endpoints and endpoint != "stock_daily_bar" and getattr(watchlist, "indices", None):
        return list(watchlist.indices)
    if hasattr(watchlist, "all_symbols"):
        return list(watchlist.all_symbols)
    return list(watchlist) if isinstance(watchlist, list) else []


def _filter_supported_symbols(
    symbols: list[str], data_source: str, endpoint: str, data_cfg: Any
) -> list[str]:
    """按接口白名单过滤配置观察池。"""
    endpoint_supports = getattr(data_cfg, "source_endpoint_supports", {})
    supports = endpoint_supports.get(data_source, {}).get(endpoint, [])
    if not supports:
        return symbols
    supported = set(supports)
    ignored = [symbol for symbol in symbols if symbol not in supported]
    if ignored:
        logger.info(
            f"数据源 [{data_source}] 接口 [{endpoint}] 仅支持白名单 {sorted(supported)}，"
            f"自动跳过不支持的标的: {ignored}"
        )
    return [symbol for symbol in symbols if symbol in supported]


def _default_symbols_for_endpoint(
    data_source: str,
    endpoint: str,
    data_cfg: Any,
    per_symbol_endpoints: set[str],
) -> list[str]:
    """按接口业务类型选择默认标的池，避免把指数池误用于个股或基金接口。"""
    local_pool = _tushare_local_pool(endpoint) if data_source == "tushare" else None
    if local_pool is not None:
        dataset, description = local_pool
        symbols = _load_curated_symbol_pool(data_source, dataset)
        if not symbols:
            raise DataFetchError(
                f"接口 [{endpoint}] 需要本地 {dataset} {description}标的池，请先完成 {dataset} 回填"
            )
        return symbols

    symbols = _watchlist_symbols(data_source, endpoint, data_cfg, per_symbol_endpoints)
    return _filter_supported_symbols(symbols, data_source, endpoint, data_cfg)


def _resolve_calendar_dates(
    fetcher: BaseDataFetcher, data_source: str, start_date: date, end_date: date
) -> list[date]:
    """获取开市有效交易日列表，支持数据源与工作日降级。"""
    fetch_trade_cal_fn = getattr(fetcher, "fetch_trade_cal", None)
    if not callable(fetch_trade_cal_fn) or data_source == "fred":
        cur = start_date
        cal_dates: list[date] = []
        while cur <= end_date:
            cal_dates.append(cur)
            cur += timedelta(days=1)
        return cal_dates

    try:
        res = fetch_trade_cal_fn(start_date, end_date)
        if isinstance(res, list):
            dates = [d for d in res if isinstance(d, date)]
            if dates:
                return dates
    except Exception as e:
        logger.warning(f"获取数据源网络交易日历失败 [{e}]，降级使用工作日...")

    cur = start_date
    cal_dates = []
    while cur <= end_date:
        if cur.weekday() < 5:
            cal_dates.append(cur)
        cur += timedelta(days=1)
    return cal_dates


def _execute_parallel_tasks(
    task_fn: Callable[[Any], bool | int],
    items: list[Any],
    max_workers: int,
    item_desc: Callable[[Any], str],
) -> tuple[int, int]:
    """多线程并发执行任务并统计成功与失败数。"""
    synced = 0
    failed = 0
    workers = min(max_workers, 8) if max_workers > 1 else 1
    if workers > 1 and len(items) > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(task_fn, item): item for item in items}
            for idx, fut in enumerate(as_completed(futures), 1):
                item = futures[fut]
                desc = item_desc(item)
                try:
                    res = fut.result()
                    if (isinstance(res, bool) and res) or (isinstance(res, int) and res > 0):
                        synced += (res if isinstance(res, int) else 1)
                        logger.info(f"[{idx}/{len(items)}] {desc} 回填成功")
                    else:
                        failed += (1 if isinstance(res, bool) else (len(item[1]) if isinstance(item, tuple) else 1))
                        logger.warning(f"[{idx}/{len(items)}] {desc} 回填失败")
                except Exception as e:
                    logger.error(f"[{idx}/{len(items)}] {desc} 抛出异常: {e}")
                    failed += (1 if isinstance(item, date) else (len(item[1]) if isinstance(item, tuple) else 1))
    else:
        for idx, item in enumerate(items, 1):
            desc = item_desc(item)
            try:
                res = task_fn(item)
                if (isinstance(res, bool) and res) or (isinstance(res, int) and res > 0):
                    synced += (res if isinstance(res, int) else 1)
                    logger.info(f"[{idx}/{len(items)}] {desc} 回填成功")
                else:
                    failed += (1 if isinstance(res, bool) else (len(item[1]) if isinstance(item, tuple) else 1))
                    logger.warning(f"[{idx}/{len(items)}] {desc} 回填失败")
            except Exception as e:
                logger.error(f"[{idx}/{len(items)}] {desc} 抛出异常: {e}")
                failed += (1 if isinstance(item, date) else (len(item[1]) if isinstance(item, tuple) else 1))
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
        self.endpoint = resolve_task(data_source, endpoint).task_name
        self._calendar_cache: dict[tuple[date, date], list[date]] = {}

        if pipeline is not None:
            self.pipeline = pipeline
            self.fetcher = fetcher or pipeline.fetcher
        else:
            self.pipeline = create_pipeline(data_source=data_source, endpoint=endpoint)
            if fetcher is not None:
                self.fetcher = fetcher
                self.pipeline.fetcher = fetcher
            else:
                self.fetcher = self.pipeline.fetcher

    @property
    def frequency(self) -> str:
        """自动在注册表中识别当前任务频次。"""
        registry_map = {
            "tushare": "stock.data.fetcher.tushare.registry",
            "yfinance": "stock.data.fetcher.yfinance.registry",
            "fred": "stock.data.fetcher.fred.registry",
        }
        mod_path = registry_map.get(self.data_source)
        if mod_path:
            import importlib

            try:
                mod = importlib.import_module(mod_path)
                reg_dict = (
                    getattr(mod, "TUSHARE_API_REGISTRY", None)
                    or getattr(mod, "YFINANCE_API_REGISTRY", None)
                    or getattr(mod, "FRED_API_REGISTRY", None)
                )
                task = resolve_task(self.data_source, self.endpoint)
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

        dates = _resolve_calendar_dates(self.fetcher, self.data_source, start_date, end_date)
        self._calendar_cache[cache_key] = dates
        return dates

    def _generate_tasks(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> list[date]:
        open_dates = self._get_open_trading_dates(start_date, end_date, use_cache=not force_refresh)
        if force_refresh:
            return open_dates

        todo_dates = []
        for idx, trade_date in enumerate(open_dates, 1):
            has_curated = getattr(self.pipeline.store, "has_curated", lambda e, d, s=None: False)(
                self.endpoint, trade_date, self.symbol
            )
            has_raw = True
            raw_store = getattr(self.pipeline, "raw_store", None)
            if not force_refresh and raw_store is not None and hasattr(raw_store, "has_raw"):
                has_raw = bool(raw_store.has_raw(self.data_source, self.endpoint, trade_date))
            if has_curated and has_raw and not force_refresh:
                continue

            if not DataUpdateScheduler.is_data_ready(
                endpoint=self.endpoint, target_date=trade_date, data_source=self.data_source
            ):
                continue
            todo_dates.append(trade_date)
        return todo_dates

    def _sync_single_day(self, trade_date: date, force_refresh: bool = False) -> bool:
        try:
            df = self.pipeline.sync_daily_bars(
                symbol=self.symbol,
                start_date=trade_date,
                end_date=trade_date,
                use_raw_cache=not force_refresh,
                force_refresh=force_refresh,
            )
            return not df.is_empty()
        except Exception as e:
            logger.error(f"交易日 [{trade_date}] 回填异常: {e}")
            return False

    def backfill_range(
        self,
        start_date: date,
        end_date: date,
        force_refresh: bool = False,
        max_workers: int = 1,
    ) -> dict[str, Any]:
        """按交易日范围进行历史数据批量回填。"""
        total_days = (end_date - start_date).days + 1
        freq = self.frequency
        task_spec = resolve_task(self.data_source, self.endpoint)

        if freq != "daily" or task_spec.fetch_mode != "per_day" or self.endpoint in MARKET_SINGLE_SYNC_ENDPOINTS:
            sym_code = self.symbol or self.endpoint
            df = self.pipeline.sync_daily_bars(
                symbol=sym_code,
                start_date=start_date,
                end_date=end_date,
                use_raw_cache=not force_refresh,
                force_refresh=force_refresh,
            )
            count = len(df) if not df.is_empty() else 0
            return {
                "total_days": total_days,
                "open_days": 1,
                "synced_days": count,
                "skipped_days": 0,
                "failed_days": 0 if count > 0 else 1,
            }

        open_dates = self._get_open_trading_dates(start_date, end_date, use_cache=not force_refresh)
        todo_dates = self._generate_tasks(start_date, end_date, force_refresh=force_refresh)
        skipped_count = len(open_dates) - len(todo_dates)
        synced_count = 0
        failed_count = 0

        if not todo_dates:
            return {
                "total_days": total_days,
                "open_days": len(open_dates),
                "synced_days": 0,
                "skipped_days": skipped_count,
                "failed_days": 0,
            }

        if not self.symbol:
            def _sync_day(d: date) -> bool:
                try:
                    df = self.pipeline.sync_daily_bars(
                        symbol="",
                        start_date=d,
                        end_date=d,
                        use_raw_cache=not force_refresh,
                        force_refresh=force_refresh,
                    )
                    return not df.is_empty()
                except Exception as e:
                    logger.error(f"全市场交易日 [{d}] 同步异常: {e}")
                    return False

            synced_count, failed_count = _execute_parallel_tasks(
                task_fn=_sync_day,
                items=todo_dates,
                max_workers=max_workers,
                item_desc=lambda d: f"交易日 [{d}] 全市场数据",
            )
        elif is_per_symbol_task(self.data_source, self.endpoint):
            b_start = min(todo_dates)
            b_end = max(todo_dates)
            try:
                df = self.pipeline.sync_daily_bars(
                    symbol=self.symbol,
                    start_date=b_start,
                    end_date=b_end,
                    use_raw_cache=not force_refresh,
                    force_refresh=force_refresh,
                )
                synced_count = len(todo_dates) if not df.is_empty() else 0
            except Exception as e:
                logger.error(f"标的 [{self.symbol}] 历史范围 [{b_start} ~ {b_end}] 回填异常: {e}")
                failed_count = len(todo_dates)
        else:
            month_batches: dict[tuple[int, int], list[date]] = {}
            for d in todo_dates:
                month_batches.setdefault((d.year, d.month), []).append(d)

            def _sync_batch(batch_tuple: tuple[tuple[int, int], list[date]]) -> int:
                _, b_dates = batch_tuple
                b_start = min(b_dates)
                b_end = max(b_dates)
                try:
                    df = self.pipeline.sync_daily_bars(
                        symbol=self.symbol,
                        start_date=b_start,
                        end_date=b_end,
                        use_raw_cache=not force_refresh,
                        force_refresh=force_refresh,
                    )
                    return len(b_dates) if not df.is_empty() else 0
                except Exception as e:
                    logger.error(f"月度批次 [{b_start} ~ {b_end}] 回填异常: {e}")
                    return 0

            synced_count, failed_count = _execute_parallel_tasks(
                task_fn=_sync_batch,
                items=list(month_batches.items()),
                max_workers=max_workers,
                item_desc=lambda t: f"月度批次 [{t[0][0]}-{t[0][1]:02d}]",
            )

        summary = {
            "total_days": total_days,
            "open_days": len(open_dates),
            "synced_days": synced_count,
            "skipped_days": skipped_count,
            "failed_days": failed_count,
        }
        return summary


__all__ = [
    "MARKET_SINGLE_SYNC_ENDPOINTS",
    "TUSHARE_STOCK_POOL_ENDPOINTS",
    "TUSHARE_FUND_POOL_ENDPOINTS",
    "HistoricalBackfiller",
    "resolve_public_task",
    "_default_symbols_for_endpoint",
    "_load_backfill_yaml_config",
]


def _load_backfill_yaml_config(
    config_path_str: str = "config/data.yaml",
) -> dict[str, Any]:
    """加载 YAML 回填配置文件。"""
    from pathlib import Path
    import yaml

    config_path = Path(config_path_str)
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
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


def main() -> None:
    """CLI 入口点 (兼容层包装)。"""
    from stock.cli.backfill import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
