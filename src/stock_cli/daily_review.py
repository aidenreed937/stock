"""每日盘后复盘 CLI 薄入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines import run_daily_review
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.daily_review",
        description="生成每日盘后全景量化复盘报告",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=date.fromisoformat,
        default=None,
        help="复盘基准日期 (YYYY-MM-DD，默认为最新交易日)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="研报落盘目录 (默认 output/reports/daily/)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="Curated 数据目录覆盖路径",
    )
    parser.add_argument(
        "--refresh-upstream",
        action="store_true",
        help="刷新市场温度和行业结构上游产物",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    args = _build_parser().parse_args()
    try:
        result = run_daily_review(
            target_date=args.as_of_date,
            output_dir=args.output_dir,
            storage_dir=args.storage_dir,
            refresh_upstream=args.refresh_upstream,
        )
    except Exception as exc:
        logger.error("生成每日复盘失败: {}", exc)
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(1) from exc
    sys.stdout.write(f"复盘研报生成成功: {result.report_path}\n")


if __name__ == "__main__":
    main()
