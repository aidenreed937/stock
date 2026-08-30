"""中观行业轮动调仓频率扫描（升级路线 P0 第一项）。

验证「月频 → 周频」是否能在扣除真实摩擦（万1佣金 + 万5滑点 + 3% 死区）后
提升净风险调整收益。对 4 个中观策略分别扫描 rebalance_period ∈ {5, 10, 20, 40}
交易日，输出净额指标（CAGR / MaxDD / Sharpe / Calmar）与年化单边换手。

净额由 ``IndustryStrategyRunner.backtest`` 扣摩擦后得到；换手由 ``runner.run``
的逐笔信号重建权重变化统计（双边 Σ|Δw|，单边 = 双边 / 2）。
"""

from __future__ import annotations

from math import sqrt
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.report import load_all_industry_strategy_specs
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool import create_strategy

_PERIODS = (5, 10, 20, 40)
_CONFIG_PATH = "config/strategy/industry_rotation.yaml"
_TRADING_DAYS_PER_YEAR = 252.0


def _metrics(nav_df: pl.DataFrame) -> dict[str, float]:
    """算术口径绩效指标（与多策略对比脚本一致）。"""
    navs = [float(v) for v in nav_df["nav"].to_list()]
    n = len(navs)
    final = navs[-1]
    years = n / _TRADING_DAYS_PER_YEAR
    cagr = (final ** (1.0 / years) - 1.0) * 100.0 if years > 0 and final > 0 else 0.0

    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    rets = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n)]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / sqrt(var_r) * sqrt(_TRADING_DAYS_PER_YEAR) if var_r > 0 else 0.0

    calmar = cagr / (max_dd * 100.0) if max_dd > 0 else 0.0
    return {
        "cagr": cagr,
        "max_drawdown": max_dd * 100.0,
        "sharpe": sharpe,
        "calmar": calmar,
    }


def _annual_turnover(runner: IndustryStrategyRunner, panel: pl.DataFrame) -> tuple[float, int]:
    """从信号序列重建权重变化，统计年化单边换手率与信号总数。"""
    report = runner.run(panel)
    weights: dict[str, float] = {}
    bilateral = 0.0
    for sig in report.signals:
        old = weights.get(sig.symbol, 0.0)
        new = float(sig.target_weight or 0.0)
        bilateral += abs(new - old)
        weights[sig.symbol] = new
    years = len(panel["trade_date"].unique()) / _TRADING_DAYS_PER_YEAR
    one_way_annual = (bilateral / 2.0) / years if years > 0 else 0.0
    return one_way_annual, len(report.signals)


def main() -> None:
    catalog = DataCatalog(data_source="tushare")
    panel = assemble_industry_panel(
        catalog=catalog, factor_root="data/analytics/industry_structure"
    )
    price_panel = load_industry_price_panel(catalog=catalog)
    specs = load_all_industry_strategy_specs(_CONFIG_PATH)

    rows: list[dict] = []
    for key, spec in specs.items():
        cls_name = str(spec.get("strategy_class", ""))
        friction = spec.get("friction", {})
        comm = float(friction.get("commission_rate", 0.0001))
        slip = float(friction.get("slippage_rate", 0.0005))
        dead = float(friction.get("rebalance_deadband", 0.03))

        for period in _PERIODS:
            kwargs = {
                k: v
                for k, v in spec.items()
                if k not in ("strategy_class", "friction", "description", "name")
            }
            kwargs["rebalance_period"] = period
            strat = create_strategy(cls_name, **kwargs)
            runner = IndustryStrategyRunner(
                strat,
                strategy_name=key,
                commission_rate=comm,
                slippage_rate=slip,
                rebalance_deadband=dead,
            )
            nav = runner.backtest(panel, price_panel)
            m = _metrics(nav)
            turnover, n_signals = _annual_turnover(runner, panel)
            rows.append(
                {
                    "strategy": key,
                    "rebalance_period": period,
                    "cagr": m["cagr"],
                    "max_drawdown": m["max_drawdown"],
                    "sharpe": m["sharpe"],
                    "calmar": m["calmar"],
                    "annual_one_way_turnover": round(turnover, 2),
                    "signals": n_signals,
                }
            )

    result = pl.DataFrame(rows)
    out_dir = Path("data/analytics/industry_strategy")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "industry_frequency_scan.csv"
    result.write_csv(csv_path)

    print("=== 中观行业轮动调仓频率扫描 (净额, 已扣万1佣金+万5滑点) ===")
    print(
        result.select(
            [
                "strategy",
                "rebalance_period",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
                "annual_one_way_turnover",
                "signals",
            ]
        )
    )

    # 结论：每个策略的 Sharpe 最优频率
    print("\n=== 各策略 Sharpe 最优频率 ===")
    for key in specs:
        sub = result.filter(pl.col("strategy") == key).sort("sharpe", descending=True)
        best = sub.to_dicts()[0]
        base = sub.filter(pl.col("rebalance_period") == 20).to_dicts()[0]
        print(
            f"{key}: 最优 {best['rebalance_period']}D (Sharpe {best['sharpe']:.2f}), "
            f"月频20D (Sharpe {base['sharpe']:.2f})"
        )

    print(f"\n明细 CSV: {csv_path}")


if __name__ == "__main__":
    main()
