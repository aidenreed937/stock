"""全市场日频聚合特征向量化计算算子 (market_daily_ops)。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.primitives.rules import (
    above_ma,
    at_rolling_high,
    at_rolling_low,
    daily_return,
    share,
)

if TYPE_CHECKING:
    from datetime import date

    from stock_core.contracts import MarketDataCatalog


def build_breadth_and_turnover(
    catalog: MarketDataCatalog,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    """从 stock_daily_bar 计算成交总额、涨跌比、站上均线占比与新高新低占比。"""
    lookback_start = (start_date - timedelta(days=500)) if start_date is not None else None

    bars = catalog.load_bars(
        start_date=lookback_start,
        end_date=end_date,
        columns=["trade_date", "symbol", "close", "amount"],
        dedup=True,
        validate=False,
    )
    if bars.is_empty() or "trade_date" not in bars.columns:
        return pl.DataFrame()

    turnover_daily = (
        bars.select(["trade_date", "amount"])
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("amount").sum().alias("total_turnover"))
    )

    clean_bars = (
        bars.select(
            "trade_date",
            pl.col("symbol").cast(pl.Utf8),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .filter(pl.col("close") > 0)
        .sort(["symbol", "trade_date"])
    )

    signals = clean_bars.with_columns(
        daily_return("close").alias("_ret_1d"),
        above_ma("close", 20).alias("_above_ma20"),
        above_ma("close", 60).alias("_above_ma60"),
        above_ma("close", 120).alias("_above_ma120"),
        at_rolling_high("close", 252).alias("_new_high_252d"),
        at_rolling_low("close", 252).alias("_new_low_252d"),
    )

    breadth_daily = (
        signals.group_by("trade_date")
        .agg(
            pl.col("symbol").n_unique().alias("total_stocks"),
            pl.col("_ret_1d").count().alias("_return_count"),
            (pl.col("_ret_1d") > 0).sum().alias("_adv_count"),
            (pl.col("_ret_1d") < 0).sum().alias("_dec_count"),
            pl.col("_above_ma20").sum().alias("_above_ma20_count"),
            pl.col("_above_ma20").count().alias("_ma20_valid"),
            pl.col("_above_ma60").sum().alias("_above_ma60_count"),
            pl.col("_above_ma60").count().alias("_ma60_valid"),
            pl.col("_above_ma120").sum().alias("_above_ma120_count"),
            pl.col("_above_ma120").count().alias("_ma120_valid"),
            pl.col("_new_high_252d").sum().alias("_new_high_count"),
            pl.col("_new_high_252d").count().alias("_high_low_valid"),
            pl.col("_new_low_252d").sum().alias("_new_low_count"),
        )
        .with_columns(
            share("_adv_count", "_dec_count", "adv_dec_ratio"),
            share("_adv_count", "_return_count", "advance_ratio"),
            share("_above_ma20_count", "_ma20_valid", "above_ma20_ratio"),
            share("_above_ma60_count", "_ma60_valid", "above_ma60_ratio"),
            share("_above_ma120_count", "_ma120_valid", "above_ma120_ratio"),
            share("_new_high_count", "_high_low_valid", "new_high_252d_ratio"),
            share("_new_low_count", "_high_low_valid", "new_low_252d_ratio"),
        )
        .select(
            "trade_date",
            "total_stocks",
            "adv_dec_ratio",
            "advance_ratio",
            "above_ma20_ratio",
            "above_ma60_ratio",
            "above_ma120_ratio",
            "new_high_252d_ratio",
            "new_low_252d_ratio",
        )
    )

    res = turnover_daily.join(breadth_daily, on="trade_date", how="full", coalesce=True)
    if start_date is not None:
        res = res.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        res = res.filter(pl.col("trade_date") <= end_date)
    return res


def build_margin_features(
    catalog: MarketDataCatalog,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """从 margin 数据集聚合两融余额与融资买入额。"""
    margin = catalog.load_dataset(
        "margin",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "rzmre", "rzye", "rqye", "rzrqye", "exchange_id"],
    )
    if margin.is_empty() or "trade_date" not in margin.columns:
        return pl.DataFrame()

    agg_exprs = []
    if "rzrqye" in margin.columns:
        agg_exprs.append(pl.col("rzrqye").sum().alias("margin_balance"))
    elif "rzye" in margin.columns:
        agg_exprs.append(pl.col("rzye").sum().alias("margin_balance"))

    if "rzmre" in margin.columns:
        agg_exprs.append(pl.col("rzmre").sum().alias("margin_buy_amount"))

    if not agg_exprs:
        return pl.DataFrame()

    return margin.group_by("trade_date").agg(agg_exprs).sort("trade_date")


def build_turnover_rate_features(
    catalog: MarketDataCatalog,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """从 daily_basic 计算全市场自由流通换手率与流通市值。"""
    basic = catalog.load_dataset(
        "daily_basic",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "turnover_rate_f", "turnover_rate", "circ_mv"],
    )
    if basic.is_empty() or "trade_date" not in basic.columns:
        return pl.DataFrame()

    turnover_col = "turnover_rate_f" if "turnover_rate_f" in basic.columns else "turnover_rate"
    has_turnover = turnover_col in basic.columns
    has_circ_mv = "circ_mv" in basic.columns

    select_cols = ["trade_date"]
    agg_exprs = []
    if has_turnover:
        select_cols.append(turnover_col)
        agg_exprs.append(
            pl.col(turnover_col).cast(pl.Float64, strict=False).mean().alias("market_turnover_rate")
        )
    if has_circ_mv:
        select_cols.append("circ_mv")
        agg_exprs.append(
            pl.col("circ_mv").cast(pl.Float64, strict=False).sum().alias("market_circ_mv")
        )

    if not agg_exprs:
        return pl.DataFrame()

    return basic.select(select_cols).group_by("trade_date").agg(agg_exprs).sort("trade_date")


def build_moneyflow_features(
    catalog: MarketDataCatalog,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """从 moneyflow 计算主力净流入额。"""
    flow = catalog.load_dataset(
        "moneyflow",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "net_mf_amount"],
    )
    if flow.is_empty() or "trade_date" not in flow.columns or "net_mf_amount" not in flow.columns:
        return pl.DataFrame()

    return (
        flow.select(
            "trade_date",
            pl.col("net_mf_amount").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("net_mf_amount").sum().alias("main_net_inflow"))
        .sort("trade_date")
    )


def build_limit_features(
    catalog: MarketDataCatalog,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """从 limit_list_d 计算涨停、跌停与炸板指标。"""
    limit = catalog.load_dataset(
        "limit_list_d",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "limit"],
    )
    if limit.is_empty() or "trade_date" not in limit.columns or "limit" not in limit.columns:
        return pl.DataFrame()

    return (
        limit.group_by("trade_date")
        .agg(
            (pl.col("limit") == "U").sum().alias("limit_up_count"),
            (pl.col("limit") == "D").sum().alias("limit_down_count"),
            (pl.col("limit") == "Z").sum().alias("broken_limit_count"),
        )
        .with_columns(
            pl.when((pl.col("limit_up_count") + pl.col("broken_limit_count")) > 0)
            .then(
                pl.col("broken_limit_count")
                / (pl.col("limit_up_count") + pl.col("broken_limit_count"))
            )
            .otherwise(None)
            .alias("broken_limit_ratio")
        )
        .sort("trade_date")
    )


def build_option_features(
    catalog: MarketDataCatalog,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """从 opt_daily 与 opt_basic 计算期权聚合指标。"""
    daily = catalog.load_dataset(
        "opt_daily",
        start_date=start_date,
        end_date=end_date,
        columns=["symbol", "trade_date", "vol", "amount", "oi"],
    )
    if daily.is_empty() or "trade_date" not in daily.columns:
        return pl.DataFrame()

    basic = catalog.load_dataset(
        "opt_basic",
        columns=["symbol", "call_put", "s_month"],
    )
    if basic.is_empty() or not {"symbol", "call_put", "s_month"}.issubset(basic.columns):
        return pl.DataFrame()

    basic_frame = basic.select(
        pl.col("symbol").cast(pl.String).alias("symbol"),
        pl.col("call_put").cast(pl.String).alias("_call_put"),
        pl.col("s_month").cast(pl.String).alias("_s_month"),
    ).drop_nulls(subset=["symbol", "_call_put", "_s_month"])

    option_frame = (
        daily.select(
            pl.col("symbol").cast(pl.String).alias("symbol"),
            "trade_date",
            pl.col("vol").cast(pl.Float64, strict=False).alias("_vol"),
            pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
            pl.col("oi").cast(pl.Float64, strict=False).alias("_oi"),
        )
        .drop_nulls(subset=["symbol", "trade_date"])
        .join(basic_frame, on="symbol", how="inner")
        .with_columns(pl.col("trade_date").dt.strftime("%Y%m").alias("_trade_month"))
    )
    if option_frame.is_empty():
        return pl.DataFrame()

    near_month = (
        option_frame.filter(pl.col("_s_month") >= pl.col("_trade_month"))
        .group_by("trade_date")
        .agg(pl.col("_s_month").min().alias("_near_month"))
    )
    option_frame = option_frame.join(near_month, on="trade_date", how="left")

    return (
        option_frame.group_by("trade_date")
        .agg(
            pl.when(pl.col("_call_put") == "P")
            .then(pl.col("_vol"))
            .otherwise(0.0)
            .sum()
            .alias("_put_vol"),
            pl.when(pl.col("_call_put") == "C")
            .then(pl.col("_vol"))
            .otherwise(0.0)
            .sum()
            .alias("_call_vol"),
            pl.when(pl.col("_call_put") == "P")
            .then(pl.col("_oi"))
            .otherwise(0.0)
            .sum()
            .alias("_put_oi"),
            pl.when(pl.col("_call_put") == "C")
            .then(pl.col("_oi"))
            .otherwise(0.0)
            .sum()
            .alias("_call_oi"),
            pl.col("_amount").sum().alias("option_amount"),
            pl.col("_oi").sum().alias("option_open_interest"),
            pl.when(pl.col("_s_month") == pl.col("_near_month"))
            .then(pl.col("_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_near_month_amount"),
        )
        .with_columns(
            pl.when(pl.col("_call_vol") > 0)
            .then(pl.col("_put_vol") / pl.col("_call_vol"))
            .otherwise(None)
            .alias("option_put_call_volume_ratio"),
            pl.when(pl.col("_call_oi") > 0)
            .then(pl.col("_put_oi") / pl.col("_call_oi"))
            .otherwise(None)
            .alias("option_put_call_oi_ratio"),
            pl.when(pl.col("option_amount") > 0)
            .then(pl.col("_near_month_amount") / pl.col("option_amount") * 100.0)
            .otherwise(None)
            .alias("option_near_month_amount_share"),
        )
        .select(
            "trade_date",
            "option_put_call_volume_ratio",
            "option_put_call_oi_ratio",
            "option_amount",
            "option_open_interest",
            "option_near_month_amount_share",
        )
        .sort("trade_date")
    )
