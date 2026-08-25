"""多日期分析 CLI 薄入口。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.multi_date_runner import run_multi_date
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按多个 A 股交易日串行生成并发布四类分析产物",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dates", nargs="+", type=_parse_date, metavar="YYYY-MM-DD")
    source.add_argument("--start", type=_parse_date, metavar="YYYY-MM-DD")
    source.add_argument("--last-n", type=_positive_int, metavar="N")
    parser.add_argument("--end", type=_parse_date, metavar="YYYY-MM-DD")
    parser.add_argument("--refresh-mart", action="store_true")
    parser.add_argument("--mart-start", type=_parse_date, metavar="YYYY-MM-DD")
    parser.add_argument("--storage-dir", type=Path, default=None)
    parser.add_argument("--analytics-root", type=Path, default=Path("data/analytics"))
    parser.add_argument("--publish-date", type=_parse_date, metavar="YYYY-MM-DD")
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
    )
    parser.add_argument(
        "--skip-metrics",
        dest="collect_metric_values",
        action="store_false",
        default=None,
    )
    parser.add_argument("--no-publish-latest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    args = _build_parser().parse_args(argv)
    try:
        result = run_multi_date(
            dates=args.dates,
            start=args.start,
            end=args.end,
            last_n=args.last_n,
            refresh_mart=args.refresh_mart,
            mart_start=args.mart_start,
            storage_dir=args.storage_dir,
            analytics_root=args.analytics_root,
            publish_date=args.publish_date,
            run_class=args.run_class,
            collect_metric_values=args.collect_metric_values,
            no_publish_latest=args.no_publish_latest,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        logger.error("多日期产物生成失败: {}", exc)
        return 1
    for message in result.messages:
        print(message)
    return 0


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期格式错误，请使用 YYYY-MM-DD: {value}") from exc


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"数量必须是正整数: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"数量必须是正整数: {value}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
