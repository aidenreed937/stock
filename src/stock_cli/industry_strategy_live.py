"""申万行业轮动盘尾 14:50 实时巡检与 ETF 报单 CLI。"""

from __future__ import annotations

import argparse
import sys

from stock_core.utils.logger import logger, setup_logger
from stock_strategy.industry.live import inspect_live_industry_signal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="申万行业轮动策略 14:50 盘尾实盘信号推演与行业 ETF 报单指令生成"
    )
    parser.add_argument(
        "--strategy",
        "-s",
        type=str,
        default="industry_momentum",
        help="指定巡检的行业策略标识 (如 industry_momentum / industry_meta_router)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/strategy/industry_rotation.yaml",
        help="策略配置文件路径",
    )
    parser.add_argument(
        "--factor-root",
        type=str,
        default="data/analytics/industry_structure",
        help="行业因子面板产物根目录",
    )
    parser.add_argument(
        "--macro-risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录",
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
        res = inspect_live_industry_signal(
            strategy_key=args.strategy,
            config_path=args.config,
            factor_root=args.factor_root,
            macro_risk_root=args.macro_risk_root,
            total_capital=args.capital,
        )
        print(res.markdown_card)
        if res.has_rebalance:
            print(
                f"\n[INFO] 策略 {args.strategy} 今日触发调仓，共生成 {len(res.instructions)} 条指令。"
            )
        else:
            print(f"\n[INFO] 策略 {args.strategy} 今日无需调仓。")
    except Exception as exc:
        logger.error(f"实盘推演执行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
