"""全市场资金博弈与筹码结构日频 Mart 构建模块。

通过对账国家队/被动 ETF、两融杠杆资金、逐笔订单流、龙虎榜席位与筹码胜率，
消除全市场成交额通胀，刻画多主体资金博弈分歧与微观状态。
"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.marts.shared.rolling_percentile import add_rolling_percentiles

CAPITAL_GAME_MART_NAME = "capital_game_daily"

#: 资金博弈状态标签枚举
STATE_BOTTOM_SUPPORT = "BOTTOM_SUPPORT"  # 国家队托底护盘底
STATE_HIGH_DISTRIBUTION = "HIGH_DISTRIBUTION"  # 主力高位派发换手顶
STATE_LEVERAGE_EUPHORIA = "LEVERAGE_EUPHORIA"  # 杠杆两融情绪狂热
STATE_ICE_PANIC = "ICE_PANIC"  # 冰点无序踩踏
STATE_ALL_RESONANCE = "ALL_RESONANCE"  # 多头资金共振主升
STATE_BALANCED_ROTATION = "BALANCED_ROTATION"  # 均衡轮动常态


def build_capital_game_frame(
    etf_flow: pl.DataFrame,
    margin: pl.DataFrame,
    moneyflow: pl.DataFrame,
    dragon_tiger: pl.DataFrame,
    block_trade: pl.DataFrame,
    cyq_perf: pl.DataFrame,
    market_turnover: pl.DataFrame,
    *,
    percentile_cutoff: date | None = None,
) -> pl.DataFrame:
    """构建全市场资金博弈日频宽表。

    Args:
        etf_flow: 来自 ``etf_flow_daily`` Mart，包含各风格 ETF 资金净流入
        margin: 来自 ``margin`` 事实表，包含融资融券买入/偿还/余额
        moneyflow: 来自 ``moneyflow`` 事实表，包含超大/大/中/小单订单流
        dragon_tiger: 来自 ``dragon_tiger_daily`` Mart，包含机构/游资净买入
        block_trade: 来自 ``block_trade_daily`` Mart，包含大宗交易折价率
        cyq_perf: 来自 ``cyq_perf`` 事实表，包含筹码胜率与平均成本
        market_turnover: 包含 ``[trade_date, total_turnover]`` 的日成交额基准
        percentile_cutoff: 增量构建的起始计算日期

    Returns:
        包含无量纲比率、5Y 滚动分位、分歧度得分与博弈状态的 Polars DataFrame
    """
    if market_turnover.is_empty() or "trade_date" not in market_turnover.columns:
        return pl.DataFrame()

    base = (
        market_turnover.select(
            pl.col("trade_date").cast(pl.Date),
            pl.col("total_turnover").cast(pl.Float64, strict=False).alias("total_turnover"),
        )
        .filter(pl.col("total_turnover").is_not_null() & (pl.col("total_turnover") > 0))
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )
    if base.is_empty():
        return pl.DataFrame()

    # 1. 提取 ETF 流向
    etf_sub = pl.DataFrame()
    if not etf_flow.is_empty() and "trade_date" in etf_flow.columns:
        etf_cols = ["trade_date"]
        for c in ("total_etf_net_inflow", "broad_etf_net_inflow", "sector_etf_net_inflow"):
            if c in etf_flow.columns:
                etf_cols.append(c)
        etf_sub = etf_flow.select(
            [pl.col("trade_date").cast(pl.Date)]
            + [pl.col(c).cast(pl.Float64, strict=False) for c in etf_cols if c != "trade_date"]
        ).unique(subset=["trade_date"], keep="last")

    # 2. 聚合两融数据 (全市场三所求和)
    margin_sub = pl.DataFrame()
    if not margin.is_empty() and "trade_date" in margin.columns:
        m_cols = [c for c in ("rzmre", "rzche", "rzye") if c in margin.columns]
        if m_cols:
            margin_sub = (
                margin.with_columns(pl.col("trade_date").cast(pl.Date))
                .group_by("trade_date")
                .agg(
                    pl.col("rzmre").cast(pl.Float64, strict=False).sum().alias("margin_buy_amount")
                    if "rzmre" in margin.columns
                    else pl.lit(0.0).alias("margin_buy_amount"),
                    pl.col("rzche")
                    .cast(pl.Float64, strict=False)
                    .sum()
                    .alias("margin_repay_amount")
                    if "rzche" in margin.columns
                    else pl.lit(0.0).alias("margin_repay_amount"),
                    pl.col("rzye").cast(pl.Float64, strict=False).sum().alias("margin_balance")
                    if "rzye" in margin.columns
                    else pl.lit(None).alias("margin_balance"),
                )
                .with_columns(
                    (pl.col("margin_buy_amount") - pl.col("margin_repay_amount")).alias(
                        "margin_net_buy_amount"
                    )
                )
            )

    # 3. 聚合订单流数据 (全市场个股超大单/大单/小单求和)
    mf_sub = pl.DataFrame()
    if not moneyflow.is_empty() and "trade_date" in moneyflow.columns:
        mf_sub = (
            moneyflow.with_columns(pl.col("trade_date").cast(pl.Date))
            .group_by("trade_date")
            .agg(
                (
                    pl.col("buy_elg_amount").cast(pl.Float64, strict=False)
                    - pl.col("sell_elg_amount").cast(pl.Float64, strict=False)
                )
                .sum()
                .alias("net_super_large_amount")
                if "buy_elg_amount" in moneyflow.columns and "sell_elg_amount" in moneyflow.columns
                else pl.lit(0.0).alias("net_super_large_amount"),
                (
                    pl.col("buy_lg_amount").cast(pl.Float64, strict=False)
                    - pl.col("sell_lg_amount").cast(pl.Float64, strict=False)
                )
                .sum()
                .alias("net_large_amount")
                if "buy_lg_amount" in moneyflow.columns and "sell_lg_amount" in moneyflow.columns
                else pl.lit(0.0).alias("net_large_amount"),
                (
                    pl.col("buy_sm_amount").cast(pl.Float64, strict=False)
                    - pl.col("sell_sm_amount").cast(pl.Float64, strict=False)
                )
                .sum()
                .alias("net_small_amount")
                if "buy_sm_amount" in moneyflow.columns and "sell_sm_amount" in moneyflow.columns
                else pl.lit(0.0).alias("net_small_amount"),
            )
            .with_columns(
                (pl.col("net_super_large_amount") + pl.col("net_large_amount")).alias(
                    "main_order_net_inflow"
                )
            )
        )

    # 4. 提取龙虎榜席位数据
    lhb_sub = pl.DataFrame()
    if not dragon_tiger.is_empty() and "trade_date" in dragon_tiger.columns:
        lhb_cols = [
            c
            for c in ("inst_net_buy_amount", "hot_money_net_buy_amount")
            if c in dragon_tiger.columns
        ]
        if lhb_cols:
            lhb_sub = dragon_tiger.select(
                [pl.col("trade_date").cast(pl.Date)]
                + [pl.col(c).cast(pl.Float64, strict=False) for c in lhb_cols]
            ).unique(subset=["trade_date"], keep="last")

    # 5. 提取大宗交易折价率
    bt_sub = pl.DataFrame()
    if not block_trade.is_empty() and "trade_date" in block_trade.columns:
        if "block_trade_discount_rate_median" in block_trade.columns:
            bt_sub = block_trade.select(
                pl.col("trade_date").cast(pl.Date),
                pl.col("block_trade_discount_rate_median").cast(pl.Float64, strict=False),
            ).unique(subset=["trade_date"], keep="last")

    # 6. 聚合筹码胜率与集中度
    cyq_sub = pl.DataFrame()
    if not cyq_perf.is_empty() and "trade_date" in cyq_perf.columns:
        cyq_exprs = []
        if "winner_rate" in cyq_perf.columns:
            cyq_exprs.append(
                pl.col("winner_rate").cast(pl.Float64, strict=False).mean().alias("winner_rate_avg")
            )
        if all(c in cyq_perf.columns for c in ("cost_5pct", "cost_95pct", "cost_50pct")):
            cyq_exprs.append(
                pl.when(pl.col("cost_50pct").cast(pl.Float64, strict=False) > 0)
                .then(
                    (
                        pl.col("cost_95pct").cast(pl.Float64, strict=False)
                        - pl.col("cost_5pct").cast(pl.Float64, strict=False)
                    )
                    / pl.col("cost_50pct").cast(pl.Float64, strict=False)
                )
                .otherwise(None)
                .median()
                .alias("chip_concentration_median")
            )
        if cyq_exprs:
            cyq_sub = (
                cyq_perf.with_columns(pl.col("trade_date").cast(pl.Date))
                .group_by("trade_date")
                .agg(cyq_exprs)
            )

    # 7. 多路左连接
    merged = base
    for frame in (etf_sub, margin_sub, mf_sub, lhb_sub, bt_sub, cyq_sub):
        if not frame.is_empty():
            merged = merged.join(frame, on="trade_date", how="left")

    # 8. 无量纲化计算 (除以成交额)
    turnover = pl.col("total_turnover")
    merged = merged.with_columns(
        # ETF 流向比率
        (pl.col("total_etf_net_inflow") / turnover).alias("etf_flow_ratio")
        if "total_etf_net_inflow" in merged.columns
        else pl.lit(None).alias("etf_flow_ratio"),
        (pl.col("broad_etf_net_inflow") / turnover).alias("broad_etf_flow_ratio")
        if "broad_etf_net_inflow" in merged.columns
        else pl.lit(None).alias("broad_etf_flow_ratio"),
        # 两融融资比率
        (pl.col("margin_net_buy_amount") / turnover).alias("margin_flow_ratio")
        if "margin_net_buy_amount" in merged.columns
        else pl.lit(None).alias("margin_flow_ratio"),
        # 订单流主力比率
        (pl.col("main_order_net_inflow") / turnover).alias("main_order_flow_ratio")
        if "main_order_net_inflow" in merged.columns
        else pl.lit(None).alias("main_order_flow_ratio"),
        (pl.col("net_small_amount") / turnover).alias("retail_order_flow_ratio")
        if "net_small_amount" in merged.columns
        else pl.lit(None).alias("retail_order_flow_ratio"),
        # 机构席位比率
        (pl.col("inst_net_buy_amount") / turnover).alias("inst_lhb_flow_ratio")
        if "inst_net_buy_amount" in merged.columns
        else pl.lit(None).alias("inst_lhb_flow_ratio"),
    )

    # 9. 滚动 5Y 百分位计算
    value_cols_for_pct: list[str] = [
        str(c)
        for c in (
            "etf_flow_ratio",
            "margin_flow_ratio",
            "main_order_flow_ratio",
            "retail_order_flow_ratio",
            "winner_rate_avg",
        )
        if c in merged.columns
    ]

    if value_cols_for_pct:
        merged = merged.with_columns(pl.lit("market").alias("_dummy_key"))
        merged = add_rolling_percentiles(
            merged,
            key="_dummy_key",
            date_column="trade_date",
            value_columns=value_cols_for_pct,
            cutoff_date=percentile_cutoff,
        ).drop(["_dummy_key"] + [f"{c}_percentile_10y" for c in value_cols_for_pct])

    # 10. 计算资金分歧度得分与微观博弈状态
    etf_p = (
        pl.col("etf_flow_ratio_percentile_5y")
        if "etf_flow_ratio_percentile_5y" in merged.columns
        else pl.lit(50.0)
    )
    main_p = (
        pl.col("main_order_flow_ratio_percentile_5y")
        if "main_order_flow_ratio_percentile_5y" in merged.columns
        else pl.lit(50.0)
    )
    margin_p = (
        pl.col("margin_flow_ratio_percentile_5y")
        if "margin_flow_ratio_percentile_5y" in merged.columns
        else pl.lit(50.0)
    )
    retail_p = (
        pl.col("retail_order_flow_ratio_percentile_5y")
        if "retail_order_flow_ratio_percentile_5y" in merged.columns
        else pl.lit(50.0)
    )
    winner = pl.col("winner_rate_avg") if "winner_rate_avg" in merged.columns else pl.lit(50.0)

    # 分歧度得分: 机构/国家队力量 - 散户/杠杆力量，归一化到 [-100, +100]
    inst_score = (etf_p.fill_null(50.0) + main_p.fill_null(50.0)) / 2.0
    retail_score = (margin_p.fill_null(50.0) + retail_p.fill_null(50.0)) / 2.0
    divergence_expr = (inst_score - retail_score).round(2).alias("divergence_score")

    # 博弈状态规则判定
    game_state_expr = (
        pl.when((etf_p >= 88.0) & ((margin_p <= 20.0) | (winner <= 15.0)))
        .then(pl.lit(STATE_BOTTOM_SUPPORT))
        .when(
            (etf_p <= 15.0)
            & (margin_p >= 85.0)
            & (pl.col("retail_order_flow_ratio").fill_null(0.0) > 0)
        )
        .then(pl.lit(STATE_HIGH_DISTRIBUTION))
        .when((margin_p >= 94.0) & ((winner >= 85.0) | winner.is_null()))
        .then(pl.lit(STATE_LEVERAGE_EUPHORIA))
        .when((main_p <= 10.0) & (margin_p <= 10.0) & (etf_p < 50.0))
        .then(pl.lit(STATE_ICE_PANIC))
        .when((etf_p >= 70.0) & (main_p >= 70.0) & (margin_p >= 65.0))
        .then(pl.lit(STATE_ALL_RESONANCE))
        .otherwise(pl.lit(STATE_BALANCED_ROTATION))
        .alias("game_state")
    )

    result = merged.with_columns(divergence_expr, game_state_expr)
    return result.sort("trade_date")


__all__ = [
    "CAPITAL_GAME_MART_NAME",
    "STATE_ALL_RESONANCE",
    "STATE_BALANCED_ROTATION",
    "STATE_BOTTOM_SUPPORT",
    "STATE_HIGH_DISTRIBUTION",
    "STATE_ICE_PANIC",
    "STATE_LEVERAGE_EUPHORIA",
    "build_capital_game_frame",
]
