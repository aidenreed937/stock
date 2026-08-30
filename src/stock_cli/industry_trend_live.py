"""产业趋势跟踪盘尾实时巡检与 ETF 报单 CLI（申万二级方向池）。"""

from __future__ import annotations

import argparse
import sys

from stock_core.utils.logger import logger, setup_logger
from stock_strategy.industry.trend_live import inspect_live_industry_trend_signal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="产业趋势跟踪策略盘尾实盘信号推演与二级行业 ETF 报单指令生成"
    )
    parser.add_argument(
        "--strategy",
        "-s",
        type=str,
        default="industry_l2_direction",
        help="指定巡检的产业趋势策略标识 (如 industry_l2_direction / industry_l2_direction_qlq)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy/industry_trend_tracking.yaml",
        help="产业趋势策略配置文件路径",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="实盘总资金规模 (元)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅本地预览报单卡片，不触发外部推送",
    )
    args = parser.parse_args()
    setup_logger()

    try:
        res = inspect_live_industry_trend_signal(
            strategy_key=args.strategy,
            config_path=args.config,
            total_capital=args.capital,
        )
        print(res.markdown_card)
        if res.has_rebalance:
            print(
                f"\n[INFO] 策略 {args.strategy} 触发调仓，共生成 {len(res.instructions)} 条指令"
                f"（dry-run={args.dry_run}）。"
            )
        else:
            print(f"\n[INFO] 策略 {args.strategy} 今日无需调仓（dry-run={args.dry_run}）。")
    except Exception as exc:
        logger.error(f"产业趋势实盘推演执行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
