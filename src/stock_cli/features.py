"""Analytics Feature 与 Domain Mart CLI 薄入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.features import build_features
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建与管理 Analytics Mart 特征宽表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build", help="构建并物化市场/行业日频特征宽表")
    build_parser.add_argument(
        "--target",
        choices=[
            "market_daily",
            "industry_daily",
            "industry_panel_daily",
            "derived_facts",
            "domain_marts",
            "all",
        ],
        default="market_daily",
        help="待构建的目标宽表或领域 Mart",
    )
    build_parser.add_argument("-s", "--start", dest="start_date", default=None)
    build_parser.add_argument("-e", "--end", dest="end_date", default=None)
    build_parser.add_argument("--overwrite", action="store_true", default=False)
    build_parser.add_argument("--storage-dir", dest="storage_dir", default=None)
    return parser


def main() -> None:
    """CLI 主入口。"""
    args = _build_parser().parse_args()
    if args.command != "build":
        return
    try:
        build_features(
            target=args.target,
            start_date=_parse_date(args.start_date) or date(2014, 1, 1),
            end_date=_parse_date(args.end_date),
            overwrite=args.overwrite,
            storage_dir=Path(args.storage_dir) if args.storage_dir else None,
        )
    except (RuntimeError, ValueError) as exc:
        logger.error("构建 Analytics Feature 失败: {}", exc)
        sys.exit(1)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"日期格式错误，请使用 YYYY-MM-DD: {value}") from exc


if __name__ == "__main__":
    main()
