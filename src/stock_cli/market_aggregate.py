"""A 股全市场配置驱动聚合监控 CLI。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from stock_analytics.pipelines.market_aggregate import run_market_aggregate
from stock_core.exceptions import DataFetchError
from stock_core.utils.logger import logger
from stock_reporting.interpretation.market_aggregate.config import DEFAULT_CONFIG_PATH


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 A 股全市场聚合监控 facts/report 产物（不输出逐标的明细）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--watch", action="store_true", help="持续监控，按配置间隔重复抓取")
    parser.add_argument("--interval", type=float, default=None, help="覆盖配置中的抓取间隔（秒）")
    parser.add_argument(
        "--format",
        choices=("table", "markdown", "human"),
        default="table",
        help="终端输出格式；human 为面向人工阅读版",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="聚合监控 YAML 配置路径")
    parser.add_argument("--output-root", default=None, help="覆盖 analytics 产物根目录")
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="产物运行分类",
    )
    parser.add_argument("--no-latest", action="store_true", help="不刷新产物根目录下的 latest")
    parser.add_argument("--record", action="store_true", help="将一行聚合快照留档到 RAW")
    parser.add_argument("--raw-root", default=None, help="聚合快照 RAW 留档根目录")
    parser.add_argument(
        "--batch-size",
        "--page-size",
        dest="batch_size",
        type=int,
        default=None,
        help="覆盖 YAML 中的腾讯单批请求标的数",
    )
    parser.add_argument(
        "--strong-move-pct",
        type=float,
        default=None,
        help="覆盖 YAML 中的强势上涨/下跌阈值（百分比）",
    )
    parser.add_argument(
        "--skip-industry",
        action="store_true",
        help="不生成行业维度切片（覆盖 YAML 中 industry.enabled）",
    )
    return parser


def main() -> None:
    """执行一次或持续执行配置驱动的全市场聚合监控。"""
    args = _build_parser().parse_args()
    try:
        interval = args.interval
        if interval is None:
            from stock_reporting.interpretation.market_aggregate.config import (
                load_market_aggregate_config,
            )

            interval = load_market_aggregate_config(Path(args.config)).interval_seconds
        while True:
            result = run_market_aggregate(
                config_path=Path(args.config),
                output_root=args.output_root,
                run_class=args.run_class,
                update_latest=not args.no_latest,
                record_raw=args.record,
                raw_root=args.raw_root,
                batch_size=args.batch_size,
                strong_move_pct=args.strong_move_pct,
                skip_industry=args.skip_industry,
            )
            output = (
                result.table_markdown
                if args.format == "table"
                else result.human_report_markdown
                if args.format == "human"
                else result.report_markdown
            )
            sys.stdout.write(f"\n{output}\n")
            sys.stdout.flush()
            if not args.watch:
                logger.info("全市场聚合监控产物已写入: {}", result.paths.run_dir.resolve())
                break
            time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        sys.stdout.write("\n已停止全市场聚合监控。\n")
    except DataFetchError as exc:
        logger.error("全市场聚合监控失败：{}", exc)
        raise SystemExit(1) from exc
    except Exception as exc:
        logger.exception("全市场聚合监控产物生成失败: {}", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
