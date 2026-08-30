"""供需质量修正：把 ind_scissors 从「净利增速−营收增速」改为「量价齐升」口径。

背景：现有 ind_scissors = 净利增速 − 营收增速，在供给收缩（营收负、利润正）时虚高，
系统性做多「虚假繁荣」（已验证：需求驱动 +0.74% vs 供给收缩 +0.29%/20日）。

修正方案（横截面 rank 0-100，双周 Top3 动量回测对比）：
- ind_scissors（现有 baseline）
- comp_qlq = (rank营收 + rank净利) / 2  量价齐升双正共振
- comp_scissors_fixed = 营收增速>0 时才用「净利−营收」，否则极低分  约束剪刀差
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool.industry_momentum import IndustryMomentumRotationStrategy

_TRADING_DAYS_PER_YEAR = 252.0


def _cs_percentile(col: str) -> pl.Expr:
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def _metrics(nav_df: pl.DataFrame) -> dict[str, float]:
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
    return {"cagr": cagr, "max_drawdown": max_dd * 100.0, "sharpe": sharpe, "calmar": calmar}


def main() -> None:
    catalog = DataCatalog(data_source="tushare")
    panel = assemble_industry_panel(
        catalog=catalog, factor_root="data/analytics/industry_structure"
    )
    price_panel = load_industry_price_panel(catalog=catalog)

    p = (
        pl.read_parquet("data/curated/mart/industry_panel_daily.parquet")
        .select(["as_of_date", "industry_code", "revenue_growth_ttm", "profit_growth_ttm"])
        .rename({"as_of_date": "trade_date"})
    )

    p = p.with_columns(
        [
            _cs_percentile("revenue_growth_ttm").alias("rev_pct"),
            _cs_percentile("profit_growth_ttm").alias("prof_pct"),
        ]
    )
    # 约束剪刀差：营收增速 > 0 才用「净利−营收」，否则极低分
    scissors_fixed_raw = (
        pl.when(pl.col("revenue_growth_ttm") > 0.0)
        .then(pl.col("profit_growth_ttm") - pl.col("revenue_growth_ttm"))
        .otherwise(-1e6)
    )
    p = p.with_columns(
        [
            ((pl.col("rev_pct") + pl.col("prof_pct")) / 2.0).alias("comp_qlq"),
            scissors_fixed_raw.alias("_scissors_fixed_raw"),
        ]
    )
    p = p.with_columns(_cs_percentile("_scissors_fixed_raw").alias("comp_scissors_fixed"))

    panel = panel.join(
        p.select(["trade_date", "industry_code", "comp_qlq", "comp_scissors_fixed"]),
        on=["trade_date", "industry_code"],
        how="left",
    )

    score_cols = ("ind_scissors", "comp_qlq", "comp_scissors_fixed")
    nav_map: dict[str, pl.DataFrame] = {}
    rows: list[dict] = []
    for score_col in score_cols:
        strat = IndustryMomentumRotationStrategy(
            top_k=3, rebalance_period=10, score_column=score_col
        )
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=f"mom_{score_col}",
            commission_rate=0.0001,
            slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price_panel)
        nav_map[score_col] = nav
        rows.append({"score": score_col, **_metrics(nav)})

    result = pl.DataFrame(rows)
    out = Path("data/analytics/industry_strategy")
    out.mkdir(parents=True, exist_ok=True)
    result.write_csv(out / "industry_scissors_fix.csv")

    print("=== 全周期（双周 10D Top3 动量，净额） ===")
    print(
        result.select(
            [
                "score",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        ).sort("sharpe", descending=True)
    )

    print("\n=== 样本外（2022-01-01 后） ===")
    oos_rows = []
    for score_col in score_cols:
        nav = nav_map[score_col].filter(pl.col("trade_date") >= date(2022, 1, 1))
        oos_rows.append({"score": score_col, **_metrics(nav)})
    oos = pl.DataFrame(oos_rows)
    print(
        oos.select(
            [
                "score",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        ).sort("sharpe", descending=True)
    )


if __name__ == "__main__":
    main()
