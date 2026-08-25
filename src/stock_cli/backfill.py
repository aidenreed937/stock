"""历史数据回填 CLI 兼容入口。"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from stock_core.config.loader import load_data_config
from stock_core.utils.logger import logger
from stock_data.pipeline.backfill_runner import (
    BackfillRequest,
    run_backfill,
)
from stock_data.pipeline.backfill_runner import (
    execute_planned_tasks as _execute_planned_tasks,
)
from stock_data.pipeline.backfill_runner import (
    parse_backfill_date as _parse_date,
)
from stock_data.pipeline.backfill_runner import (
    resolve_universe_symbols as _resolve_universe_symbols,
)

__all__ = [
    "_execute_planned_tasks",
    "_parse_date",
    "_resolve_universe_symbols",
    "main",
]


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A 股全市场历史数据回填与断点续传引擎")
    parser.add_argument("--start", "--start-date", dest="start_date")
    parser.add_argument("--end", "--end-date", dest="end_date")
    parser.add_argument(
        "--source",
        "--data-source",
        dest="data_source",
        help="数据源 (tushare/yfinance/fred/lixinger)",
    )
    parser.add_argument("--endpoint", help="接口名称 (逗号分隔)")
    parser.add_argument("--symbol", help="股票/指数/基金代码 (逗号分隔或 'watchlist')")
    parser.add_argument("--config", help="回填 YAML 配置文件路径")
    parser.add_argument("--universe", help="股票池配置名称")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--max-workers", type=int)
    return parser


def _format_summary_table(summaries: list[dict[str, Any]]) -> None:
    """打印回填摘要统计表。"""
    logger.info("=" * 105)
    logger.info("历史数据回填任务执行摘要汇总:")
    logger.info(
        f"{'数据源':<10} | {'接口/数据集':<22} | {'标的':<14} | {'总日历日':<8} | "
        f"{'交易日':<8} | {'已同步':<8} | {'已跳过':<8} | {'失败':<6}"
    )
    logger.info("-" * 105)
    for summary in summaries:
        logger.info(
            f"{summary.get('data_source', '')!s: <10} | "
            f"{summary.get('endpoint', '')!s: <22} | "
            f"{summary.get('symbol', '')!s: <14} | "
            f"{summary.get('total_days', 0): <8} | "
            f"{summary.get('open_days', 0): <8} | "
            f"{summary.get('synced_days', 0): <8} | "
            f"{summary.get('skipped_days', 0): <8} | "
            f"{summary.get('failed_days', 0): <6}"
        )
    logger.info("=" * 105)


def main() -> None:
    """解析参数并调用历史回填 Facade。"""
    args = _build_argument_parser().parse_args()
    request = BackfillRequest(
        data_source=args.data_source,
        endpoint=args.endpoint,
        symbol=args.symbol,
        universe=args.universe,
        start_date=_parse_date(args.start_date),
        end_date=_parse_date(args.end_date),
        config=args.config,
        force_refresh=args.force_refresh,
        max_workers=args.max_workers,
    )
    summaries = run_backfill(request, data_cfg=load_data_config())
    _format_summary_table(summaries)
    failed_items = [
        item
        for item in summaries
        if isinstance(value := item.get("failed_days"), int | float) and value > 0
    ]
    failed_days = sum(
        int(value)
        for item in failed_items
        if isinstance(value := item.get("failed_days"), int | float)
    )
    if failed_days:
        logger.error(
            f"历史数据回填存在失败任务，失败交易日数合计: {failed_days}, 失败项清单: {failed_items}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
