"""历史数据回填命令行 (CLI) 接口逻辑。"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from stock.config.loader import load_data_config
from stock.data.backfill import (
    MARKET_SINGLE_SYNC_ENDPOINTS,
    _default_symbols_for_endpoint,
    _load_backfill_yaml_config,
    resolve_public_task,
)
from stock.data.task_registry import is_per_symbol_task
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


def main() -> None:  # noqa: C901, PLR0912, PLR0915
    """CLI 入口点。"""
    parser = argparse.ArgumentParser(description="金融历史数据回填与增量补全 CLI")
    parser.add_argument(
        "--config",
        type=str,
        default="config/data.yaml",
        help="回填配置文件路径",
    )
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="source",
        type=str,
        default=None,
        help="数据源 (tushare/yfinance/lixinger/fred/mock)。若未指定则自动从 data.yaml 读取",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="回填的项目任务名或 API 名称 (默认回填配置中所有 enabled 接口)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="回填目标代码 ('600519.SH'，'all' 全市场，'watchlist' 自选池)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default=None,
        help="使用的选股池名称或配置，自动覆盖 --symbol 为选中池标的",
    )
    parser.add_argument(
        "--start",
        "--start-date",
        dest="start_date",
        type=str,
        default=None,
        help="回填起始日期 (YYYY-MM-DD 或 YYYYMMDD)",
    )
    parser.add_argument(
        "--end",
        "--end-date",
        dest="end_date",
        type=str,
        default=None,
        help="回填结束日期 (YYYY-MM-DD 或 YYYYMMDD)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="强制重新拉取并覆盖已精炼离线归档"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="抓取并发线程数 (覆盖默认配置)",
    )

    args = parser.parse_args()

    yaml_config = _load_backfill_yaml_config(args.config)
    data_cfg = load_data_config()

    data_source = (
        args.source
        or yaml_config.get("source")
        or yaml_config.get("default_data_source")
        or data_cfg.default_source_mode
        or "tushare"
    )
    endpoint = args.endpoint or yaml_config.get("endpoint") or yaml_config.get("default_endpoint")
    symbol = (
        args.symbol
        if args.symbol is not None
        else (yaml_config.get("symbol") or yaml_config.get("default_symbol", "all"))
    )
    if symbol == "watchlist":
        symbol = ""
    force_refresh = args.force_refresh or yaml_config.get("force_refresh", False)

    def parse_dt(d_str: str | None) -> date | None:
        if not d_str:
            return None
        d_clean = d_str.strip().lower()
        if d_clean == "today":
            return date.today()
        if "today-" in d_clean:
            import re

            m = re.search(r"today-(\d+)", d_clean)
            if m:
                return date.today() - timedelta(days=int(m.group(1)))
        d_clean = d_clean.replace("-", "")
        return datetime.strptime(d_clean, "%Y%m%d").date()

    start_d = (
        parse_dt(args.start_date)
        or parse_dt(yaml_config.get("start_date"))
        or parse_dt(yaml_config.get("default_start_date"))
        or date(2024, 1, 1)
    )
    end_d = (
        parse_dt(args.end_date)
        or parse_dt(yaml_config.get("end_date"))
        or parse_dt(yaml_config.get("default_end_date"))
        or date.today()
    )

    if endpoint is None:
        from stock.data.task_registry import list_available_tasks

        configured_targets = list_available_tasks(data_source)
        endpoint = "stock_daily_bar" if not configured_targets else ",".join(configured_targets)

    workers = args.max_workers
    if workers is None:
        workers = yaml_config.get("max_workers")
    if workers is None:
        workers = getattr(
            data_cfg.concurrency,
            f"{data_source}_max_workers",
            data_cfg.concurrency.default_max_workers,
        )

    from stock.constants import ENDPOINT_START_DATE_OVERRIDES

    start_overrides = (
        getattr(data_cfg, "endpoint_start_date_overrides", {}) or ENDPOINT_START_DATE_OVERRIDES
    )
    if endpoint in start_overrides:
        min_supported = date.fromisoformat(start_overrides[endpoint])
        if start_d < min_supported:
            logger.info(
                f"接口 [{endpoint}] 触发历史起始日自动截断校准: 原 [{start_d}] "
                f"自动提升至官方上线首日 [{min_supported}]"
            )
            start_d = min_supported

    universe_symbols: list[str] | None = None
    if args.universe:
        uni_path = Path(f"config/universe/{args.universe}.yaml")
        if uni_path.exists():
            try:
                with uni_path.open("r", encoding="utf-8") as f:
                    uni_data = yaml.safe_load(f)
                    if uni_data and "universe" in uni_data and "stocks" in uni_data["universe"]:
                        configured_symbols = [str(item) for item in uni_data["universe"]["stocks"]]
                        universe_symbols = configured_symbols
                        symbol = ""
                        logger.info(
                            f"从配置文件 [{uni_path}] 载入股票池，"
                            f"共 {len(configured_symbols)} 只标的。"
                        )

            except Exception as e:
                logger.error(f"加载股票池配置文件失败: {e}")
                sys.exit(1)
        else:
            from stock.data.storage.duckdb_store import DuckDBMarketStore

            store = DuckDBMarketStore(data_source="tushare")
            df_snapshots = store.query_universe_snapshots()
            if not df_snapshots.is_empty() and "symbol" in df_snapshots.columns:
                latest_as_of = df_snapshots["as_of_date"].max()
                df_latest_snap = df_snapshots.filter(df_snapshots["as_of_date"] == latest_as_of)
                universe_symbols = df_latest_snap["symbol"].unique().to_list()
                symbol = ""
                logger.info(
                    f"成功直接从 DuckDB 选股快照数据库 (as_of_date={latest_as_of!s}) "
                    f"载入股票池，共 {len(universe_symbols)} 只标的。"
                )
            else:
                logger.error(
                    f"找不到股票池配置文件 [{uni_path}]，且 DuckDB 选股快照库为空！"
                    "请先运行 `make filter-universe` 生成股票池快照。"
                )
                sys.exit(1)

    endpoints = []
    for raw_endpoint in (ep.strip() for ep in endpoint.split(",") if ep.strip()):
        try:
            endpoints.append(resolve_public_task(data_source, raw_endpoint).task_name)
        except ValueError as exc:
            logger.error(str(exc))
            sys.exit(2)

    from stock.data.storage.duckdb_store import DuckDBMarketStore

    shared_store = DuckDBMarketStore(data_source=data_source)
    if hasattr(shared_store, "enable_batch_mode"):
        shared_store.enable_batch_mode()

    summaries: list[dict[str, object]] = []
    try:
        for ep_idx, current_ep in enumerate(endpoints, 1):
            logger.info(
                f"\n{'=' * 105}\n"
                f"  [单一 CLI 进程串行安全调度 ({ep_idx}/{len(endpoints)})] "
                f"开始回填接口: [{data_source}/{current_ep}]\n"
                f"{'=' * 105}\n"
            )

            current_is_per_symbol = is_per_symbol_task(data_source, current_ep)
            is_single_sync = current_ep in MARKET_SINGLE_SYNC_ENDPOINTS and not symbol
            is_all_non_per_symbol = symbol == "all" and not current_is_per_symbol
            if is_single_sync or is_all_non_per_symbol:
                target_symbols = [""]
            elif symbol and symbol not in ("all", "watchlist"):
                target_symbols = [symbol]
            else:
                ep_filter = {current_ep} if current_is_per_symbol else set()
                target_symbols = universe_symbols or _default_symbols_for_endpoint(
                    data_source, current_ep, data_cfg, ep_filter
                )
                if not target_symbols:
                    if current_is_per_symbol:
                        raise DataFetchError(
                            f"接口 [{data_source}/{current_ep}] 未解析到按标的回填所需的目标池"
                        )
                    target_symbols = [""]

            for idx, sym in enumerate(target_symbols, 1):
                if sym:
                    logger.info(
                        f"===> 处理 [{data_source}/{current_ep}] 标的 [{sym}] "
                        f"({idx}/{len(target_symbols)})..."
                    )
                import stock.data.backfill as backfill_module

                backfiller = backfill_module.HistoricalBackfiller(
                    data_source=data_source, endpoint=current_ep, symbol=sym
                )

                backfiller.pipeline.store = shared_store

                summary = backfiller.backfill_range(
                    start_d, end_d, force_refresh=force_refresh, max_workers=workers
                )
                if isinstance(summary, dict):
                    summaries.append(
                        {
                            "endpoint": current_ep,
                            "symbol": sym,
                            **summary,
                        }
                    )

                if idx % 5 == 0 and hasattr(shared_store, "commit"):
                    shared_store.commit()
                    shared_store.enable_batch_mode()

            if hasattr(shared_store, "commit"):
                shared_store.commit()
                shared_store.enable_batch_mode()
    finally:
        if hasattr(shared_store, "commit"):
            shared_store.commit()

    failed_days = sum(
        value for item in summaries if isinstance(value := item.get("failed_days", 0), int)
    )
    if failed_days:
        logger.error(f"历史数据回填存在失败任务，失败交易日数合计: {failed_days}")
        sys.exit(1)


if __name__ == "__main__":
    main()
