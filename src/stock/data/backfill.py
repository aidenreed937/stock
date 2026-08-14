"""全市场历史数据回填调度器 (HistoricalBackfiller)。

支持按自定义历史日期范围（如过去 5 年、10 年）进行交易日历自动对齐、断点续传与两层 ETL 数据回填。
"""

import argparse
from datetime import date, datetime, timedelta
from typing import Any

from stock.data.factory import create_pipeline
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import resolve_public_task, resolve_task
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
    if frame.is_empty() or "symbol" not in frame.columns:
        return []
    return sorted(
        {
            str(symbol).strip()
            for symbol in frame.get_column("symbol").drop_nulls().to_list()
            if str(symbol).strip()
        }
    )


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
    if (
        endpoint in per_symbol_endpoints
        and endpoint != "stock_daily_bar"
        and getattr(watchlist, "indices", None)
    ):
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
        """初始化历史数据回填器。

        Args:
            pipeline: MarketDataPipeline 实例，若为 None 则自动根据 fetcher 创建。
            fetcher: 数据抓取器，若为 None 则默认使用 TuShareDataFetcher。
            data_source: 数据源标识名称（默认 tushare）。
            endpoint: 项目任务名（默认 stock_daily_bar）。
            symbol: 标的代码或行业代码。
        """
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
        """自动在注册表中识别当前项目任务的更新频次。"""
        registry_map = {
            "tushare": "stock.data.fetcher.tushare.registry",
            "yfinance": "stock.data.fetcher.yfinance.registry",
            "fred": "stock.data.fetcher.fred.registry",
        }
        module_path = registry_map.get(self.data_source)
        if module_path:
            import importlib

            try:
                mod = importlib.import_module(module_path)
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
        """获取开市有效交易日列表，支持内存与离线 Raw 缓存。

        Raises:
            DataFetchError: 当抓取器未实现交易日历接口或获取日历失败时抛出。
        """
        cache_key = (start_date, end_date)
        if use_cache and cache_key in self._calendar_cache:
            logger.info(
                f"命中内存交易日历缓存 [{start_date} ~ {end_date}]: 共 {len(self._calendar_cache[cache_key])} 个有效开市交易日"
            )
            return self._calendar_cache[cache_key]

        fetch_trade_cal_fn = getattr(self.fetcher, "fetch_trade_cal", None)
        if not callable(fetch_trade_cal_fn) or self.data_source == "fred":
            from datetime import timedelta
            cur = start_date
            cal_dates: list[date] = []
            while cur <= end_date:
                cal_dates.append(cur)
                cur += timedelta(days=1)
            logger.info(
                f"数据源 [{type(self.fetcher).__name__}] 自动使用自然日历 [{start_date} ~ {end_date}]: 共 {len(cal_dates)} 天"
            )
            self._calendar_cache[cache_key] = cal_dates
            return cal_dates

        try:
            res = fetch_trade_cal_fn(start_date, end_date)
            if isinstance(res, list):
                cal_dates = [d for d in res if isinstance(d, date)]
                if cal_dates:
                    logger.info(
                        f"交易日历从数据源获取成功 [{start_date} ~ {end_date}]: 共 {len(cal_dates)} 个有效开市交易日（已写入内存缓存）"
                    )
                    self._calendar_cache[cache_key] = cal_dates
                    return cal_dates
        except Exception as e:
            logger.warning(f"获取数据源网络交易日历失败 [{e}]，降级使用标准交易日 (工作日) 降级列表...")
            from datetime import timedelta
            cur = start_date
            cal_dates = []
            while cur <= end_date:
                if cur.weekday() < 5:
                    cal_dates.append(cur)
                cur += timedelta(days=1)
            self._calendar_cache[cache_key] = cal_dates
            return cal_dates

        from datetime import timedelta
        cur = start_date
        cal_dates = []
        while cur <= end_date:
            if cur.weekday() < 5:
                cal_dates.append(cur)
            cur += timedelta(days=1)
        self._calendar_cache[cache_key] = cal_dates
        return cal_dates

    def _generate_tasks(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> list[date]:
        """生成并筛选需要进行数据同步的交易日任务列表（支持断点续传与时间窗口拦截）。"""
        open_dates = self._get_open_trading_dates(
            start_date, end_date, use_cache=not force_refresh
        )

        if force_refresh:
            return open_dates

        todo_dates = []
        for idx, trade_date in enumerate(open_dates, 1):
            # 检查断点续传：只有在精炼层（Curated Store）存在数据时，才认为该日真正完成
            has_curated = getattr(self.pipeline.store, "has_curated", lambda e, d, s=None: False)(
                self.endpoint, trade_date, self.symbol
            )
            has_raw = True
            raw_store = getattr(self.pipeline, "raw_store", None)
            if not force_refresh and raw_store is not None and hasattr(raw_store, "has_raw"):
                has_raw = bool(raw_store.has_raw(self.data_source, self.endpoint, trade_date))
            if has_curated and has_raw and not force_refresh:
                logger.debug(
                    f"[{idx}/{len(open_dates)}] 命中精炼层归档 [{trade_date}]，断点续传自动跳过"
                )
                continue

            # 检查时间窗口：防未到更新时间的盘中/盘后无效拉取
            if not DataUpdateScheduler.is_data_ready(
                endpoint=self.endpoint,
                target_date=trade_date,
                data_source=self.data_source,
            ):
                logger.info(
                    f"[{idx}/{len(open_dates)}] 交易日 [{trade_date}] 数据未到预计更新时间，安全跳过拉取"
                )
                continue

            todo_dates.append(trade_date)
        return todo_dates

    def _sync_single_day(self, trade_date: date, force_refresh: bool = False) -> bool:
        """执行单日两层 ETL 管道数据补全。返回同步是否成功。"""
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
        """按交易日范围进行历史数据批量回填（支持并发）。

        Args:
            start_date: 回填开始日期。
            end_date: 回填结束日期.
            force_refresh: 是否强制向 API 拉取最新数据并覆盖 RAW 离线归档（默认 False）。
            max_workers: 并发回填线程数（默认 1）。

        Returns:
            dict[str, Any]: 包含回填统计信息的字典。
        """
        total_days = (end_date - start_date).days + 1
        freq = self.frequency
        task_spec = resolve_task(self.data_source, self.endpoint)

        # 对于非日频或非按日切片接口（如月频 CPI、季频财报、事件驱动及宏观全区间接口），自动执行单次全区间同步
        if freq != "daily" or task_spec.fetch_mode != "per_day" or self.endpoint in MARKET_SINGLE_SYNC_ENDPOINTS:
            logger.info(
                f"识别到接口 [{self.data_source}/{self.endpoint}] (模式: {task_spec.fetch_mode}) "
                f"执行单次全区间超高速同步 ({start_date} ~ {end_date})..."
            )
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

        open_dates = self._get_open_trading_dates(
            start_date, end_date, use_cache=not force_refresh
        )

        logger.info(
            f"开始历史数据回填 [{self.data_source}/{self.endpoint}] "
            f"(时间段: {start_date} ~ {end_date}, 自然日: {total_days}, 交易日: {len(open_dates)})"
        )

        todo_dates = self._generate_tasks(start_date, end_date, force_refresh=force_refresh)
        skipped_count = len(open_dates) - len(todo_dates)
        synced_count = 0
        failed_count = 0

        if not todo_dates:
            summary = {
                "total_days": total_days,
                "open_days": len(open_dates),
                "synced_days": 0,
                "skipped_days": skipped_count,
                "failed_days": 0,
            }
            logger.info(
                f"历史数据回填完成总结: 交易日={summary['open_days']}, "
                f"同步成功=0, 断点跳过={summary['skipped_days']}, 失败=0"
            )
            return summary

        if not self.symbol:
            # 全市场数据回填模式：必须按日同步（TuShare 限制全市场拉取必须传单个 trade_date）
            logger.info(f"全市场数据回填模式激活，将按日并发同步共 {len(todo_dates)} 个交易日...")

            def _sync_single_day_task(trade_date: date) -> bool:
                try:
                    df = self.pipeline.sync_daily_bars(
                        symbol="",
                        start_date=trade_date,
                        end_date=trade_date,
                        use_raw_cache=not force_refresh,
                        force_refresh=force_refresh,
                    )
                    return not df.is_empty()
                except Exception as e:
                    logger.error(f"全市场交易日 [{trade_date}] 同步异常: {e}")
                    return False

            if todo_dates:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                # 全市场日频拉取，适当调高并发度
                workers = min(max_workers, 8) if max_workers > 1 else 1
                if workers > 1 and len(todo_dates) > 1:
                    logger.info(f"使用 ThreadPoolExecutor 逐日并发回填，线程数: {workers}")
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        futures = {executor.submit(_sync_single_day_task, d): d for d in todo_dates}
                        for idx, fut in enumerate(as_completed(futures), 1):
                            d = futures[fut]
                            try:
                                success = fut.result()
                                if success:
                                    synced_count += 1
                                    logger.info(f"[{idx}/{len(todo_dates)}] 交易日 [{d}] 全市场数据回填成功")
                                else:
                                    failed_count += 1
                                    logger.warning(f"[{idx}/{len(todo_dates)}] 交易日 [{d}] 全市场数据回填失败")
                            except Exception as e:
                                logger.error(f"[{idx}/{len(todo_dates)}] 交易日 [{d}] 抛出异常: {e}")
                                failed_count += 1
                else:
                    for idx, d in enumerate(todo_dates, 1):
                        success = _sync_single_day_task(d)
                        if success:
                            synced_count += 1
                            logger.info(f"[{idx}/{len(todo_dates)}] 交易日 [{d}] 全市场数据回填成功")
                        else:
                            failed_count += 1
        else:
            # 单只股票/指数回填模式：对于支持整段拉取的接口，直接 1 次请求完成整段范围抓取，避免拆成月度切片触发限频
            from stock.data.task_registry import is_per_symbol_task

            if is_per_symbol_task(self.data_source, self.endpoint):
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
                    logger.info(
                        f"标的 [{self.symbol}] 历史范围 [{b_start} ~ {b_end}] 单次超高速全量回填完成 (共 {len(df)} 条记录)"
                    )
                except Exception as e:
                    logger.error(
                        f"标的 [{self.symbol}] 历史范围 [{b_start} ~ {b_end}] 回填异常: {e}"
                    )
                    failed_count = len(todo_dates)
            else:
                # 将待处理交易日按月打成分组批次 (Monthly Batch Range Packing)
                month_batches: dict[tuple[int, int], list[date]] = {}
                for d in todo_dates:
                    month_batches.setdefault((d.year, d.month), []).append(d)

                def _sync_month_batch(batch_dates: list[date]) -> int:
                    b_start = min(batch_dates)
                    b_end = max(batch_dates)
                    try:
                        df = self.pipeline.sync_daily_bars(
                            symbol=self.symbol,
                            start_date=b_start,
                            end_date=b_end,
                            use_raw_cache=not force_refresh,
                            force_refresh=force_refresh,
                        )
                        return len(batch_dates) if not df.is_empty() else 0
                    except Exception as e:
                        logger.error(f"月度批次 [{b_start} ~ {b_end}] 回填异常: {e}")
                        return 0

                batch_items = list(month_batches.items())
                if batch_items:
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    workers = min(max_workers, 4) if max_workers > 1 else 1

                    if workers > 1 and len(batch_items) > 1:
                        logger.info(
                            f"使用 ThreadPoolExecutor 进行按月多线程回填，月批次数: {len(batch_items)}, 线程数: {workers}"
                        )
                        with ThreadPoolExecutor(max_workers=workers) as month_executor:
                            month_futures = {
                                month_executor.submit(_sync_month_batch, dates): (ym, dates)
                                for ym, dates in batch_items
                            }
                            for idx, month_fut in enumerate(as_completed(month_futures), 1):
                                (ym, dates) = month_futures[month_fut]
                                try:
                                    count = month_fut.result()
                                    if count > 0:
                                        synced_count += count
                                        logger.info(
                                            f"[{idx}/{len(batch_items)}] 月度批次 [{ym[0]}-{ym[1]:02d}] "
                                            f"回填成功 (成功包含 {count} 个交易日)"
                                        )
                                    else:
                                        failed_count += len(dates)
                                        logger.warning(
                                            f"[{idx}/{len(batch_items)}] 月度批次 [{ym[0]}-{ym[1]:02d}] 回填失败"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"[{idx}/{len(batch_items)}] 月度批次 [{ym[0]}-{ym[1]:02d}] 抛出异常: {e}"
                                    )
                                    failed_count += len(dates)
                    else:
                        for idx, (ym, dates) in enumerate(batch_items, 1):
                            count = _sync_month_batch(dates)
                            if count > 0:
                                synced_count += count
                                logger.info(
                                    f"[{idx}/{len(batch_items)}] 月度批次 [{ym[0]}-{ym[1]:02d}] "
                                    f"回填成功 (成功包含 {count} 个交易日)"
                                )
                            else:
                                failed_count += len(dates)
                                logger.warning(
                                    f"[{idx}/{len(batch_items)}] 月度批次 [{ym[0]}-{ym[1]:02d}] 回填失败"
                                )

        summary = {
            "total_days": total_days,
            "open_days": len(open_dates),
            "synced_days": synced_count,
            "skipped_days": skipped_count,
            "failed_days": failed_count,
        }

        logger.info(
            f"历史数据回填完成总结: 交易日={summary['open_days']}, "
            f"同步成功={summary['synced_days']}, 断点跳过={summary['skipped_days']}, 失败={summary['failed_days']}"
        )
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
