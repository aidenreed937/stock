"""中观行业增强复合因子回测对比（升级路线 P0 第 1 项）。

基于单因子 IC 检验（industry_factor_ic.py）的结论：`industry_panel_daily` 里被
`factor_panel.py` 浪费的「分析师超预期 / 业绩预告景气」字段有正 IC，其中
`report_rc_revision`（研报上调占比）IC 4.67% 是最强单因子，碾压现有量价因子
（ma_bias 2.14%）。本脚本把 IC 为正的字段转横截面 rank 后等权合成「增强复合因子」，
用双周（10D）动量策略回测，对比现有 `ind_momentum` 的净额 Sharpe。

无前视：所有因子字段来自 `industry_panel_daily`（已按公告日点内对齐）。
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
# IC 检验中下期 20 日 IC 为正、胜率 > 53% 的字段（等权合成，避免当期 IC 加权过拟合）
_ENHANCED_FACTORS = {
    "report_rc_revision_ratio": "report_rc_revision_ratio",
    "forecast_positive_share": "forecast_positive_share",
    "forecast_p_change_mid_median": "forecast_p_change_mid_median",
    "ma_bias_20d": "ma_bias_20d",
    "money_net_inflow_share_5d": "money_net_inflow_share_5d",
    "express_roe_median": "express_roe_median",
    "express_profit_growth_median": "express_profit_growth_median",
}


def _cs_percentile(col: str) -> pl.Expr:
    """横截面百分位 (0-100)，缺失中性 50（与 factor_panel.py 一致）。"""
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

    # 1. 从 industry_panel_daily 提取增强字段，转横截面 rank
    p_daily = (
        pl.read_parquet("data/curated/mart/industry_panel_daily.parquet")
        .select(["as_of_date", "industry_code", *_ENHANCED_FACTORS.values()])
        .rename({"as_of_date": "trade_date"})
    )

    rank_exprs = [
        _cs_percentile(col).alias(f"{name}_pct") for name, col in _ENHANCED_FACTORS.items()
    ]
    p_daily = p_daily.with_columns(rank_exprs)

    pct = {name: f"{name}_pct" for name in _ENHANCED_FACTORS}
    # 聚焦合成方案（避免等权稀释最强因子 report_rc_revision）
    p_daily = p_daily.with_columns(
        [
            pl.col(pct["report_rc_revision_ratio"]).alias("comp_rc_only"),
            ((pl.col(pct["report_rc_revision_ratio"]) + pl.col(pct["ma_bias_20d"])) / 2.0).alias(
                "comp_rc_ma"
            ),
            (
                (
                    pl.col(pct["report_rc_revision_ratio"])
                    + pl.col(pct["forecast_positive_share"])
                    + pl.col(pct["forecast_p_change_mid_median"])
                )
                / 3.0
            ).alias("comp_rc_fc"),
            (
                (
                    pl.col(pct["report_rc_revision_ratio"])
                    + pl.col(pct["ma_bias_20d"])
                    + pl.col(pct["money_net_inflow_share_5d"])
                )
                / 3.0
            ).alias("comp_rc_ma_money"),
        ]
    )

    # 2. join 到现有面板
    panel = panel.join(
        p_daily.select(
            [
                "trade_date",
                "industry_code",
                "comp_rc_only",
                "comp_rc_ma",
                "comp_rc_fc",
                "comp_rc_ma_money",
            ]
        ),
        on=["trade_date", "industry_code"],
        how="left",
    )

    # 3. 双周 Top3 动量回测，对比多个 score，并保留 nav 做样本外验证
    score_cols = ("ind_momentum", "comp_rc_only", "comp_rc_ma", "comp_rc_fc", "comp_rc_ma_money")
    rows: list[dict] = []
    nav_map: dict[str, pl.DataFrame] = {}
    for score_col in score_cols:
        strat = IndustryMomentumRotationStrategy(
            top_k=3,
            rebalance_period=10,
            score_column=score_col,
        )
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=f"momentum_{score_col}",
            commission_rate=0.0001,
            slippage_rate=0.0005,
            rebalance_deadband=0.03,
        )
        nav = runner.backtest(panel, price_panel)
        nav_map[score_col] = nav
        m = _metrics(nav)
        rows.append({"score": score_col, **m})

    result = pl.DataFrame(rows)
    out = Path("data/analytics/industry_strategy")
    out.mkdir(parents=True, exist_ok=True)
    result.write_csv(out / "industry_enhanced_factor.csv")

    print("=== 双周(10D) Top3 动量：现有因子 vs 增强复合因子 (净额, 全周期) ===")
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

    # 4. 样本外验证（2022-01-01 后，对齐国泰海通分界）
    oos_rows: list[dict] = []
    for score_col in ("ind_momentum", "comp_rc_ma", "comp_rc_ma_money"):
        nav = nav_map[score_col].filter(pl.col("trade_date") >= date(2022, 1, 1))
        m = _metrics(nav)
        oos_rows.append({"score": score_col, **m})
    oos_result = pl.DataFrame(oos_rows)
    print("\n=== 样本外 (2022-01-01 后) 对比 ===")
    print(
        oos_result.select(
            [
                "score",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
            ]
        ).sort("sharpe", descending=True)
    )


if __name__ == "__main__":
    main()
