"""宏观风控策略 CLI 入口（V3 单宽基 / V4 哑铃轮动）。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import yaml

from stock_core.utils.logger import logger, setup_logger
from stock_data.catalog import DataCatalog
from stock_strategy.macro_assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro_runner import MacroRiskRunner
from stock_strategy.pool import create_strategy

DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")

_TRADING_DAYS_PER_YEAR = 252.0


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    return payload if isinstance(payload, dict) else {}


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _summarize_nav(nav: list[float]) -> dict[str, float | None]:
    if not nav:
        return {}
    n_days = max(len(nav) - 1, 0)
    total_return = nav[-1] - 1.0
    annual = nav[-1] ** (_TRADING_DAYS_PER_YEAR / n_days) - 1.0 if n_days > 0 else None

    daily = [nav[i] / nav[i - 1] - 1.0 for i in range(1, len(nav))]
    vol: float | None = None
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        variance = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
        vol = sqrt(variance) * sqrt(_TRADING_DAYS_PER_YEAR)
    sharpe = annual / vol if annual is not None and vol and vol > 0 else None

    peak = nav[0]
    max_dd = 0.0
    for value in nav:
        peak = max(peak, value)
        max_dd = max(max_dd, 1.0 - value / peak)
    return {
        "total_return": total_return,
        "annual_return": annual,
        "annual_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行宏观风控策略并输出信号与净值。")
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="策略键（对应 config/strategy/macro_risk.yaml 中的键名）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出配置文件中所有可用的策略",
    )
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--risk-root", type=str, default=str(DEFAULT_RISK_ROOT))
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    args = parser.parse_args()
    setup_logger()

    config = _load_config(Path(args.config))
    available_strategies = config.get("strategies", {})

    if args.list:
        print("当前配置中已注册的宏观策略：")
        for key, spec in available_strategies.items():
            print(
                f"  - {key}: {spec.get('strategy_class')} (基准: {spec.get('benchmark_symbol')}, 标的: {spec.get('symbols')})"
            )
        sys.exit(0)

    if not args.strategy:
        logger.error("请指定 --strategy <策略名>，或使用 --list 查看可用策略。")
        sys.exit(1)

    entry = available_strategies.get(args.strategy)
    if not entry:
        logger.error(
            "未找到策略配置: %s (可用策略: %s)",
            args.strategy,
            list(available_strategies.keys()),
        )
        sys.exit(1)

    cls_name = str(entry.get("strategy_class", ""))
    symbols = tuple(entry["symbols"])
    initial_weights = entry.get("initial_weights", {})
    benchmark = entry["benchmark_symbol"]

    friction = dict(entry.get("friction", {}))
    commission_rate = float(friction.get("commission_rate", entry.get("commission_rate", 0.0)))
    slippage_rate = float(friction.get("slippage_rate", entry.get("slippage_rate", 0.0)))
    rebalance_deadband = float(
        friction.get("rebalance_deadband", entry.get("rebalance_deadband", 0.0))
    )

    strategy_kwargs: dict[str, Any] = {
        "symbols": symbols,
        "initial_weights": initial_weights,
        "benchmark_symbol": benchmark,
    }
    for k, v in entry.items():
        if k not in {
            "strategy_class",
            "symbols",
            "initial_weights",
            "benchmark_symbol",
            "friction",
        }:
            strategy_kwargs[k] = v

    try:
        strategy = create_strategy(
            cls_name,
            **strategy_kwargs,
        )
    except Exception as exc:
        logger.error("创建策略实例失败: %s", exc)
        sys.exit(1)

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)

    catalog = DataCatalog(data_source="tushare")
    panel = assemble_macro_panel(
        catalog=catalog,
        benchmark_symbol=benchmark,
        risk_root=args.risk_root,
        start_date=start,
        end_date=end,
    )
    if panel.is_empty():
        logger.error("信号面板为空，请先运行宏观风险管线 (macro_risk)")
        sys.exit(1)

    price_panel = load_price_panel(catalog=catalog, symbols=symbols, start_date=start, end_date=end)

    runner = MacroRiskRunner(
        strategy,
        symbols=symbols,
        initial_weights=initial_weights,
        strategy_name=args.strategy,
        data_source="tushare",
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        rebalance_deadband=rebalance_deadband,
    )
    report = runner.run(panel)
    nav_frame = runner.backtest(panel, price_panel)
    nav_values = nav_frame["nav"].to_list() if not nav_frame.is_empty() else []

    min_date = panel["trade_date"].min()
    max_date = panel["trade_date"].max()
    print(f"策略: {args.strategy}")
    print(f"窗口: {min_date!s} -> {max_date!s} ({len(panel)} 交易日)")
    print(f"信号数: {len(report.signals)}")
    stats = _summarize_nav([float(v) for v in nav_values])
    print("回测净值统计:")
    print(f"  总收益: {stats.get('total_return'):.2%}")
    if stats.get("annual_return") is not None:
        print(f"  年化收益: {stats.get('annual_return'):.2%}")
    if stats.get("annual_volatility") is not None:
        print(f"  年化波动: {stats.get('annual_volatility'):.2%}")
    if stats.get("sharpe") is not None:
        print(f"  夏普比率: {stats.get('sharpe'):.2f}")
    print(f"  最大回撤: {stats.get('max_drawdown'):.2%}")

    if report.signals:
        print("最近信号:")
        for sig in report.signals[-5:]:
            print(
                f"  {sig.timestamp} {sig.symbol} {sig.direction.name} "
                f"weight={sig.target_weight} {sig.reason}"
            )


if __name__ == "__main__":
    main()
