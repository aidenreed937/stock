"""申万行业轮动单策略运行与回测 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_core.utils.logger import logger, setup_logger
from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.report import (
    compute_metrics,
    load_all_industry_strategy_specs,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool import create_strategy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="申万行业轮动单策略运行与回测工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--list",
        dest="list_strategies",
        action="store_true",
        help="列出所有已配置的行业轮动策略",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        dest="strategy_name",
        default="industry_momentum",
        help="指定运行的策略名称",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/strategy/industry_rotation.yaml",
        help="策略配置文件路径",
    )
    parser.add_argument(
        "--factor-root",
        dest="factor_root",
        default="data/analytics/industry_structure",
        help="行业因子面板产物根目录",
    )
    parser.add_argument(
        "--macro-risk-root",
        dest="macro_risk_root",
        default="data/analytics/macro_risk",
        help="宏观风险雷达产物根目录",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    setup_logger()
    parser = _build_parser()
    args = parser.parse_args()

    cfg_path = Path(args.config_path)
    specs = load_all_industry_strategy_specs(cfg_path)

    if args.list_strategies:
        print("已注册的申万行业轮动策略列表:")
        for name, spec in specs.items():
            print(f"  - {name}: {spec.get('description', '')} ({spec.get('strategy_class')})")
        return

    if args.strategy_name not in specs:
        logger.error(f"未找到策略: {args.strategy_name}，可选: {list(specs.keys())}")
        sys.exit(1)

    spec = specs[args.strategy_name]
    cls_name = str(spec.get("strategy_class", ""))

    try:
        catalog = DataCatalog(data_source="tushare")
        panel = assemble_industry_panel(
            catalog=catalog,
            factor_root=args.factor_root,
            macro_risk_root=args.macro_risk_root,
        )
        price_panel = load_industry_price_panel(catalog=catalog)

        friction = spec.get("friction", {})
        comm = float(friction.get("commission_rate", 0.0001))
        slip = float(friction.get("slippage_rate", 0.0005))
        dead = float(friction.get("rebalance_deadband", 0.03))

        kwargs = {
            k: v
            for k, v in spec.items()
            if k not in ("strategy_class", "friction", "description", "name")
        }
        strat = create_strategy(cls_name, **kwargs)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=args.strategy_name,
            commission_rate=comm,
            slippage_rate=slip,
            rebalance_deadband=dead,
        )

        nav_df = runner.backtest(panel, price_panel)
        metrics = compute_metrics(nav_df)

        print("\n==================================================")
        print(f"策略: {args.strategy_name} ({cls_name}) 回测结果")
        print("==================================================")
        print(f"累计净值:     {metrics['final_nav']:.4f}")
        print(f"总收益率:     {metrics['total_return']:+.2f}%")
        print(f"年化复合收益: {metrics['cagr']:+.2f}%")
        print(f"最大回撤:     {metrics['max_drawdown']:.2f}%")
        print(f"年化波动率:   {metrics['annual_volatility']:.2f}%")
        print(f"夏普比率:     {metrics['sharpe_ratio']:.2f}")
        print(f"卡玛比率:     {metrics['calmar_ratio']:.2f}")
        print("==================================================\n")

    except Exception as exc:
        logger.exception(f"策略回测失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
