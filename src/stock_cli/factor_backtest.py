"""因子组合回测 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_analytics.pipelines.factor_portfolio import (
    DEFAULT_CONFIG_PATH as FACTOR_PORTFOLIO_CONFIG,
)
from stock_core.utils.logger import logger
from stock_strategy.portfolio.application import run_backtest_application


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="读取因子组合分数面板并执行 top-N 等权调仓回测，产出收益/风险报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=str(FACTOR_PORTFOLIO_CONFIG),
        help="因子组合 YAML 配置路径（提供默认调仓参数）",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="回测产物根目录",
    )
    parser.add_argument(
        "--portfolio-root",
        dest="portfolio_root",
        default=None,
        help="组合分数产物根目录",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Curated 数据根目录",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="每期持仓数量（覆盖配置）",
    )
    parser.add_argument(
        "--rebalance-days",
        type=int,
        default=None,
        help="调仓周期（交易日，覆盖配置）",
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
        help="不刷新 data/analytics/factor_backtest/latest/",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result = run_backtest_application(
            config_path=Path(args.config_path),
            output_root=args.output_root,
            storage_dir=args.storage_dir,
            portfolio_root=args.portfolio_root,
            top_n=args.top_n,
            rebalance_days=args.rebalance_days,
            run_class=args.run_class,
            update_latest=bool(args.update_latest),
        )
    except Exception as exc:
        logger.exception("因子组合回测失败: {}", exc)
        sys.exit(1)
    stats = result.report_json["stats"]
    sys.stdout.write(
        f"因子组合回测完成：总收益 {(stats.get('total_return') or 0):+.2%}，"
        f"年化 {(stats.get('annual_return') or 0):+.2%}，"
        f"最大回撤 {(stats.get('max_drawdown') or 0):.2%}\n"
    )
    logger.info("因子组合回测产物已写入: {}", result.paths.run_dir.resolve())


if __name__ == "__main__":
    main()
