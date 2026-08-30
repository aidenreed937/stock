"""现实景气进攻 + 拥挤度防守 复合因子回测（修正框架）。

基于分样本内/外 IC 结论：现实景气（业绩预告 forecast / 快报 express）样本外走强，
拥挤度 tcr 样本外负向放大（风险翻倍）。本脚本构造「景气 rank + 反拥挤」复合 score，
双周 Top3 动量回测，重点看样本外（2022 后）Sharpe 是否站得住（基线 ind_momentum 0.35）。

方案：
- comp_prosperity   = (forecast + express) / 2           纯现实景气
- comp_prosperity_ac= (forecast + express + 反拥挤) / 3  景气 + 拥挤度等权三腿
- comp_prosperity_acw= 0.5*景气 + 0.5*反拥挤             景气:反拥挤 = 1:1
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
    cagr = (
        ((final / navs[0]) ** (1.0 / years) - 1.0) * 100.0
        if years > 0 and final > 0 and navs[0] > 0
        else 0.0
    )
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
        .select(
            [
                "as_of_date",
                "industry_code",
                "forecast_positive_share",
                "express_profit_growth_median",
                "forecast_p_change_mid_median",
                "tcr_percentile",
            ]
        )
        .rename({"as_of_date": "trade_date"})
    )

    p = p.with_columns(
        [
            _cs_percentile("forecast_positive_share").alias("fc_pct"),
            _cs_percentile("express_profit_growth_median").alias("ex_pct"),
            _cs_percentile("forecast_p_change_mid_median").alias("fcp_pct"),
        ]
    )
    anti_crowd = (100.0 - pl.col("tcr_percentile").fill_null(50.0)).alias("anti_crowd")
    p = p.with_columns(
        [
            anti_crowd,
            ((pl.col("fc_pct") + pl.col("ex_pct")) / 2.0).alias("comp_prosperity"),
            (
                (
                    pl.col("fc_pct")
                    + pl.col("ex_pct")
                    + (100.0 - pl.col("tcr_percentile").fill_null(50.0))
                )
                / 3.0
            ).alias("comp_prosperity_ac"),
            (
                0.5 * (pl.col("fc_pct") + pl.col("ex_pct")) / 2.0
                + 0.5 * (100.0 - pl.col("tcr_percentile").fill_null(50.0))
            ).alias("comp_prosperity_acw"),
        ]
    )

    panel = panel.join(
        p.select(
            [
                "trade_date",
                "industry_code",
                "comp_prosperity",
                "comp_prosperity_ac",
                "comp_prosperity_acw",
            ]
        ),
        on=["trade_date", "industry_code"],
        how="left",
    )

    score_cols = (
        "ind_momentum",
        "comp_prosperity",
        "comp_prosperity_ac",
        "comp_prosperity_acw",
    )
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
    result.write_csv(out / "industry_prosperity_crowd.csv")

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
