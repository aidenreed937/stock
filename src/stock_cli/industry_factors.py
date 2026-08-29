"""申万 31 行业中观 5 大因子特征面板生成 CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from stock_analytics.pipelines.industry_structure import (
    build_industry_factor_panel,
    save_industry_factor_panel,
)
from stock_core.utils.logger import logger, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成申万 31 行业 5 大中观量化因子特征面板 (industry_factor_panel.parquet)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--as-of",
        dest="as_of_date",
        default=None,
        help="指定基准日期 (YYYY-MM-DD, 默认最新交易日)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        dest="output_dir",
        default="data/analytics/industry_structure",
        help="因子产物输出目录",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/analytics/industry_factors.yaml",
        help="因子配置文件路径",
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
        help="不刷新 latest 快捷目录",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    setup_logger()
    parser = _build_parser()
    args = parser.parse_args()

    as_of = None
    if args.as_of_date:
        try:
            as_of = date.fromisoformat(args.as_of_date)
        except ValueError:
            logger.error(f"无效日期格式: {args.as_of_date}")
            sys.exit(1)

    try:
        logger.info("开始生成申万 31 行业 5 大中观因子面板...")
        panel = build_industry_factor_panel(as_of=as_of, config_path=args.config_path)
        paths = save_industry_factor_panel(
            panel,
            output_dir=args.output_dir,
            as_of=as_of,
            update_latest=bool(args.update_latest),
            run_class=args.run_class,
        )
        print(f"申万行业 5 大中观因子面板已生成: {paths.run_dir}")
        print(f"总记录数: {len(panel)}, 交易日数: {panel['trade_date'].n_unique()}")
    except Exception as exc:
        logger.exception(f"生成因子面板失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
