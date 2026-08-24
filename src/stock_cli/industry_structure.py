"""行业结构分析 CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.industry_structure import run_industry_structure
from stock_core.utils.logger import logger
from stock_reporting.interpretation.industry_structure.config import DEFAULT_CONFIG_PATH


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成申万行业结构 facts/panel/scores/report 产物",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="target_date",
        default=None,
        help="指定分析基准日期 (YYYY-MM-DD, 默认最新落盘申万行业交易日)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=str(DEFAULT_CONFIG_PATH),
        help="行业结构 YAML 配置路径",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="覆盖产物根目录",
    )
    parser.add_argument(
        "--run-class",
        choices=("official", "backfill", "experiment"),
        default="official",
        help="产物运行分类",
    )
    parser.add_argument(
        "--no-latest",
        dest="update_latest",
        action="store_false",
        help="不刷新 data/analytics/industry_structure/latest",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()
    target_date = _parse_date(args.target_date)
    try:
        result = run_industry_structure(
            target_date=target_date,
            config_path=Path(args.config_path),
            output_root=args.output_root,
            run_class=args.run_class,
            update_latest=bool(args.update_latest),
        )
    except Exception as exc:
        logger.exception("行业结构分析生成失败: {}", exc)
        sys.exit(1)
    sys.stdout.write(result.report_markdown)
    logger.info("行业结构分析产物已写入: {}", result.paths.run_dir.resolve())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD: {}", value)
        sys.exit(1)


if __name__ == "__main__":
    main()
