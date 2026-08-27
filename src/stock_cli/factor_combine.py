"""因子组合分数 CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.factor_portfolio import (
    DEFAULT_CONFIG_PATH,
    run_factor_portfolio,
)
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按因子准入报告通过子集合成每日组合分数面板",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--end-date",
        dest="end_date",
        default=None,
        help="组合窗口截止日期 (YYYY-MM-DD, 默认今天)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=str(DEFAULT_CONFIG_PATH),
        help="因子组合 YAML 配置路径",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="覆盖产物根目录",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Curated 数据根目录",
    )
    parser.add_argument(
        "--factor-research-dir",
        dest="research_dir",
        default=None,
        help="因子准入报告产物根目录（默认取配置 factor_research_dir 或相邻 factor_research）",
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
        help="不刷新 data/analytics/factor_portfolio/latest/",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result = run_factor_portfolio(
            end_date=_parse_date(args.end_date),
            config_path=Path(args.config_path),
            output_root=args.output_root,
            storage_dir=args.storage_dir,
            research_dir=args.research_dir,
            run_class=args.run_class,
            update_latest=bool(args.update_latest),
        )
    except Exception as exc:
        logger.exception("因子组合分数合成失败: {}", exc)
        sys.exit(1)
    factors = result.summary["factors"]
    sys.stdout.write(
        f"因子组合分数完成：{result.summary['factor_pool_size']} 个因子"
        f"（{'/'.join(f['feature_id'] for f in factors)}），"
        f"{result.summary['score_rows']} 行分数\n"
    )
    logger.info("因子组合分数产物已写入: {}", result.paths.run_dir.resolve())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"无效日期格式: {value}（应为 YYYY-MM-DD）") from None


if __name__ == "__main__":
    main()
