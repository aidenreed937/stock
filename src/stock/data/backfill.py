"""全市场历史数据回填调度器 (HistoricalBackfiller)。

支持按自定义历史日期范围（如过去 5 年、10 年）进行交易日历自动对齐、断点续传与两层 ETL 数据回填。
"""

import argparse
from datetime import date, datetime, timedelta
from typing import Any

from stock.data.factory import create_pipeline
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.data.update_scheduler import DataUpdateScheduler
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


class HistoricalBackfiller:
    """生产级历史数据回填调度引擎。"""

    def __init__(
        self,
        pipeline: MarketDataPipeline | None = None,
        fetcher: BaseDataFetcher | None = None,
        data_source: str = "tushare",
        endpoint: str = "daily",
        symbol: str = "",
    ) -> None:
        """初始化历史数据回填器。

        Args:
            pipeline: MarketDataPipeline 实例，若为 None 则自动根据 fetcher 创建。
            fetcher: 数据抓取器，若为 None 则默认使用 TuShareDataFetcher。
            data_source: 数据源标识名称（默认 tushare）。
            endpoint: API 接口名称（默认 daily）。
            symbol: 标的代码或行业代码。
        """
        self.symbol = symbol
        self.data_source = data_source
        self.endpoint = endpoint
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
        """自动在注册表中识别并获取当前 endpoint 的更新频次 (daily | monthly | quarterly | event)。"""
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
                if reg_dict and self.endpoint in reg_dict:
                    return getattr(reg_dict[self.endpoint], "frequency", "daily")
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
        if not callable(fetch_trade_cal_fn):
            raise DataFetchError(
                f"数据源抓取器 [{type(self.fetcher).__name__}] 未实现 fetch_trade_cal 交易日历接口，无法进行历史回填！"
            )

        try:
            res = fetch_trade_cal_fn(start_date, end_date)
            if isinstance(res, list):
                cal_dates: list[date] = [d for d in res if isinstance(d, date)]
                if cal_dates:
                    logger.info(
                        f"交易日历从数据源获取成功 [{start_date} ~ {end_date}]: 共 {len(cal_dates)} 个有效开市交易日（已写入内存缓存）"
                    )
                    self._calendar_cache[cache_key] = cal_dates
                    return cal_dates
        except Exception as e:
            logger.error(f"获取数据源交易日历失败: {e}")
            raise DataFetchError(f"获取交易日历失败: {e}") from e

        raise DataFetchError(
            f"交易日历接口返回空数据 [{start_date} ~ {end_date}]，无法进行历史回填！"
        )

    def _generate_tasks(
        self, start_date: date, end_date: date, force_refresh: bool = False
    ) -> list[date]:
        """生成并筛选需要进行数据同步的交易日任务列表（支持断点续传与时间窗口拦截）。"""
        open_dates = self._get_open_trading_dates(
            start_date, end_date, use_cache=not force_refresh
        )

        todo_dates = []
        for idx, trade_date in enumerate(open_dates, 1):
            # 检查断点续传：只有在精炼层（Curated Store）存在数据时，才认为该日真正完成
            has_curated = getattr(self.pipeline.store, "has_curated", lambda e, d, s=None: False)(
                self.endpoint, trade_date, self.symbol
            )
            if has_curated and not force_refresh:
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

        # 对于非日频接口（如月频 CPI/利率、季频财报 GDP、事件驱动），自动识别并执行单次全区间精准同步，彻底避免按交易日开市重复拉取
        if freq != "daily":
            logger.info(
                f"识别到接口 [{self.data_source}/{self.endpoint}] 注册更新频次为 [{freq}]，执行单次区间精准同步 ({start_date} ~ {end_date})..."
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
            # 单只股票/指数回填模式：按月合并批次同步，减少 API 调用
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全市场历史数据回填工具")
    parser.add_argument(
        "--config",
        type=str,
        default="config/backfill.yaml",
        help="回填配置文件路径 (默认: config/backfill.yaml)",
    )
    parser.add_argument("--start", type=str, default=None, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="data_source",
        type=str,
        default=None,
        help="数据源标识名称 (如 tushare / yfinance)",
    )
    parser.add_argument(
        "--endpoint", type=str, default=None, help="API 接口名称 (如 daily / daily_basic)"
    )
    parser.add_argument(
        "--symbol", type=str, default=None, help="标的代码或行业代码 (可选, all 表示全市场, watchlist 表示观察池)"
    )
    parser.add_argument(
        "--force-refresh", action="store_true", default=None, help="强制从 API 重新拉取并覆盖本地缓存"
    )
    parser.add_argument(
        "--max-workers", type=int, default=None, help="并发同步线程数 (若未指定，自动读取配置文件或 data.yaml 并发设置)"
    )
    return parser.parse_args()


def _parse_date_str(date_str: str) -> date:
    date_str = date_str.strip().lower()
    if date_str == "today":
        return date.today()
    if date_str.startswith("today"):
        offset_str = date_str[5:].replace(" ", "")
        if offset_str.endswith("d"):
            try:
                days = int(offset_str[:-1])
                return date.today() + timedelta(days=days)
            except ValueError:
                pass
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def main() -> None:
    import sys
    import yaml
    from pathlib import Path

    args = _parse_args()

    # 1. 尝试加载回填配置文件
    yaml_config = {}
    config_path = Path(args.config)
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f)
                if cfg_data and "backfill" in cfg_data:
                    yaml_config = cfg_data["backfill"]
                    logger.info(f"成功载入回填配置文件: {config_path}")
        except Exception as e:
            logger.warning(f"加载回填配置文件 [{args.config}] 失败: {e}，将仅使用命令行参数。")

    # 2. 合并参数优先级 (命令行传入 > 配置文件预设)
    start_str = args.start or yaml_config.get("default_start_date")
    end_str = args.end or yaml_config.get("default_end_date")

    if not start_str or not end_str:
        logger.error(
            "缺少回填的开始日期 (--start) 或结束日期 (--end)，且未在配置文件中找到 default_start_date / default_end_date。"
        )
        sys.exit(1)

    start_d = _parse_date_str(start_str)
    end_d = _parse_date_str(end_str)

    data_source = args.data_source or yaml_config.get("default_data_source")
    if not data_source:
        logger.error(
            "缺少回填的数据源参数 (--source / --data-source / -s)，且未在配置文件中找到 default_data_source。"
        )
        sys.exit(1)

    endpoint = args.endpoint or yaml_config.get("default_endpoint") or "daily"

    symbol = args.symbol
    if symbol is None:
        symbol = yaml_config.get("default_symbol", "")
    if symbol == "watchlist":
        symbol = ""

    force_refresh = args.force_refresh
    if force_refresh is None:
        force_refresh = yaml_config.get("force_refresh", False)

    from stock.config.loader import load_data_config

    data_cfg = load_data_config()

    # 3. 确定并发线程数：命令行 -> 回填配置文件 -> 对应数据源通用并发数 -> 默认线程数
    workers = args.max_workers
    if workers is None:
        workers = yaml_config.get("max_workers")
    if workers is None:
        workers = getattr(
            data_cfg.concurrency,
            f"{data_source}_max_workers",
            data_cfg.concurrency.default_max_workers,
        )

    wl = getattr(data_cfg.watchlists, data_source, None)
    if wl is not None:
        if endpoint == "index_daily" and hasattr(wl, "indices") and wl.indices:
            raw_symbols = wl.indices
        elif hasattr(wl, "all_symbols"):
            raw_symbols = wl.all_symbols
        elif isinstance(wl, list):
            raw_symbols = wl
        else:
            raw_symbols = []
    else:
        raw_symbols = []

    if symbol == "all" and endpoint != "index_daily":
        target_symbols = [""]
    else:
        target_symbols = [symbol] if (symbol and symbol not in ("all", "watchlist")) else raw_symbols
        if not target_symbols:
            target_symbols = [""]

    if len(target_symbols) > 1 or (len(target_symbols) == 1 and target_symbols[0]):
        if not symbol:
            logger.info(
                f"未显式指定 --symbol，自动载入数据源 [{data_source}] 默认观察股票池 "
                f"(共 {len(target_symbols)} 个标的): {target_symbols}"
            )

    from stock.data.storage.duckdb_store import DuckDBMarketStore
    shared_store = DuckDBMarketStore(data_source=data_source)
    if hasattr(shared_store, "enable_batch_mode"):
        shared_store.enable_batch_mode()

    try:
        for idx, sym in enumerate(target_symbols, 1):
            if sym:
                logger.info(f"===> 开始处理数据源 [{data_source}] 标的 [{sym}] ({idx}/{len(target_symbols)})...")
            backfiller = HistoricalBackfiller(
                data_source=data_source, endpoint=endpoint, symbol=sym
            )

            # 注入共享的批量存储引擎，解决写放大问题
            backfiller.pipeline.store = shared_store

            backfiller.backfill_range(
                start_d, end_d, force_refresh=force_refresh, max_workers=workers
            )

            # 每回填完 50 个股票，定期落盘一次，防止撑爆内存
            if idx % 50 == 0:
                if hasattr(shared_store, "commit"):
                    shared_store.commit()
                    shared_store.enable_batch_mode()
    finally:
        # 确保进程退出前或全部执行完毕后最后一次提交落盘
        if hasattr(shared_store, "commit"):
            shared_store.commit()


if __name__ == "__main__":
    main()
