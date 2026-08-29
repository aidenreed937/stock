"""宏观风控管线：产业资本类原始数据提取器。

与 ``data_fetchers`` 主模块分离，控制单文件规模（类规模门禁上限 400 行）。
"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.macro_risk.data_fetchers import (
    FetchContext,
    register_fetcher,
)


@register_fetcher("corporate")
def fetch_corporate(ctx: FetchContext) -> pl.DataFrame:
    """获取产业资本行为：20日滚动回购金额、董监高净买入、董监高减持及解禁压力金额。"""
    cal = ctx.md.select(["trade_date"]).sort("trade_date")
    try:
        rep = ctx.fs.get_domain_mart("repurchase_daily")
    except Exception:
        rep = pl.DataFrame()
    try:
        ins = ctx.fs.get_domain_mart("insider_activity_daily")
    except Exception:
        ins = pl.DataFrame()
    try:
        unl = ctx.fs.get_domain_mart("unlock_pressure_daily")
    except Exception:
        unl = pl.DataFrame()

    if (
        not rep.is_empty()
        and "announcement_date" in rep.columns
        and "repurchase_amount" in rep.columns
    ):
        rep_sub = (
            cal.join(
                rep.select(
                    pl.col("announcement_date").cast(pl.Date).alias("trade_date"),
                    pl.col("repurchase_amount").cast(pl.Float64, strict=False),
                ),
                on="trade_date",
                how="left",
            )
            .fill_null(0.0)
            .with_columns(
                pl.col("repurchase_amount").rolling_sum(window_size=20).alias("repurchase_amount")
            )
        )
    else:
        rep_sub = cal.with_columns(pl.lit(0.0).alias("repurchase_amount"))

    if (
        not ins.is_empty()
        and "announcement_date" in ins.columns
        and "insider_net_buy_amount" in ins.columns
        and "insider_sell_amount" in ins.columns
    ):
        ins_sub = (
            cal.join(
                ins.select(
                    pl.col("announcement_date").cast(pl.Date).alias("trade_date"),
                    pl.col("insider_net_buy_amount").cast(pl.Float64, strict=False),
                    pl.col("insider_sell_amount").cast(pl.Float64, strict=False),
                ),
                on="trade_date",
                how="left",
            )
            .fill_null(0.0)
            .with_columns(
                pl.col("insider_net_buy_amount")
                .rolling_sum(window_size=20)
                .alias("insider_net_buy_amount"),
                pl.col("insider_sell_amount")
                .rolling_sum(window_size=20)
                .alias("insider_sell_amount"),
            )
        )
    else:
        ins_sub = cal.with_columns(
            pl.lit(0.0).alias("insider_net_buy_amount"),
            pl.lit(0.0).alias("insider_sell_amount"),
        )

    if not unl.is_empty() and "trade_date" in unl.columns and "unlock_amount" in unl.columns:
        unl_sub = (
            cal.join(
                unl.select(
                    pl.col("trade_date").cast(pl.Date),
                    pl.col("unlock_amount").cast(pl.Float64, strict=False),
                ),
                on="trade_date",
                how="left",
            )
            .fill_null(0.0)
            .with_columns(
                pl.col("unlock_amount").rolling_sum(window_size=20).alias("unlock_amount")
            )
        )
    else:
        unl_sub = cal.with_columns(pl.lit(0.0).alias("unlock_amount"))

    return (
        rep_sub.join(ins_sub, on="trade_date", how="left")
        .join(unl_sub, on="trade_date", how="left")
        .sort("trade_date")
    )
