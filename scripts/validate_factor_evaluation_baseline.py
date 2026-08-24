"""因子检验体系真实数据基线验证（Phase 1, Ground Truth First）。

从本地 Curated 黄金表加载数据，对 pe_ttm / turnover_rate / 20日动量 三个因子
计算 Rank IC/ICIR/t、5 分组分层与多空组合，输出基线数值。
"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.primitives.factor_evaluation import (
    add_forward_returns,
    ic_summary,
    rank_ic_series,
)
from stock_analytics.primitives.factor_quantile import (
    quantile_forward_returns,
    quantile_summary,
)
from stock_analytics.primitives.momentum import calculate_momentum
from stock_data.catalog import DataCatalog

CATALOG = DataCatalog()
START = date(2025, 6, 1)
IC_START = date(2025, 8, 1)


def load_panel() -> pl.DataFrame:
    """加载日线 + 每日估值，拼出因子面板。"""
    bars = CATALOG.load_dataset(
        "stock_daily_bar",
        start_date=START,
        end_date=date(2026, 8, 21),
        columns=["symbol", "trade_date", "close"],
    ).sort(["symbol", "trade_date"])
    basic = CATALOG.load_dataset(
        "daily_basic",
        start_date=START,
        end_date=date(2026, 8, 21),
        columns=["symbol", "trade_date", "pe_ttm", "turnover_rate"],
    )
    panel = bars.join(basic, on=["symbol", "trade_date"], how="left")
    panel = calculate_momentum(panel, windows=(20,))
    panel = add_forward_returns(panel, horizons=(1, 5, 20), price_col="close")
    return panel.filter(pl.col("trade_date") >= IC_START)


def main() -> None:
    panel = load_panel()
    print(f"面板: {panel.height} 行, 日期 {panel['trade_date'].min()} ~ {panel['trade_date'].max()}")
    print(f"标的数: {panel['symbol'].n_unique()}")

    factors = ["pe_ttm", "turnover_rate", "mom_20d"]
    fwds = ["fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d"]

    print("\n=== Rank IC 汇总（不年化 ICIR 为主 / 年化 / t 统计量）===")
    for factor in factors:
        ic = rank_ic_series(panel, factor, fwds)
        summary = ic_summary(ic)
        print(f"\n[{factor}]")
        for row in summary.iter_rows(named=True):
            print(
                f"  {row['horizon']:<12} n={row['n_days']:<4} "
                f"IC={row['ic_mean']:.4f} ICIR={row['icir']:.3f} "
                f"ICIR_ann={row['icir_annualized']:.3f} t={row['t_stat']:.2f} "
                f"pos={row['ic_positive_ratio']:.2f} cumIC={row['cum_ic']:.3f}"
            )

    print("\n=== 5 分组分层与多空组合（fwd_ret_20d）===")
    for factor in factors:
        panel_quant = quantile_forward_returns(panel, factor, "fwd_ret_20d", n_bins=5)
        summary = quantile_summary(panel_quant, n_bins=5)
        print(f"\n[{factor}]")
        for row in summary["by_bucket"].iter_rows(named=True):
            print(
                f"  bucket={row['bucket']} n_days={row['n_days']} "
                f"n_stocks={row['n_stocks']} 加权均值={row['weighted_mean']:.3f}%"
            )
        print(
            f"  单调性 Spearman={summary['monotonicity_spearman']:.3f} "
            f"Top-Bottom={summary['long_short_mean']:.3f}% "
            f"多空最大回撤={summary['long_short_max_drawdown']:.3f}%"
        )


if __name__ == "__main__":
    main()
