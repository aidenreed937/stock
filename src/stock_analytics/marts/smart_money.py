"""聪明钱组合信号领域 Mart：产业资本增持 + 大宗折价接盘 + 国家队股东锚点。

三个子信号（各自 0-100 滚动分位）等权合成日频 ``smart_money_score``，
刻画"知情 + 逆势接货型资金"的净买入强度。资金有效性实证见
``data/analytics/macro_strategy/smart_money_composite.md``。

口径与 PIT：
1. 产业资本增持: ``insider_activity_daily`` 董监高净增持 20 日滚动和,
   1250 日滚动分位（announcement_date 对齐, 公告日才可用）;
2. 大宗折价接盘: ``block_trade_daily`` 每日 金额×折价深度
   （折价率 = 成交价/当日收盘价-1, 折价为负）, 250 日滚动分位;
3. 国家队股东锚点: ``top10_floatholders`` 汇金/证金/社保/梧桐树净增持
   （ann_date 对齐, asof 生效）, 500 日滚动分位。
"""

from __future__ import annotations

import polars as pl

from stock_analytics.primitives.rules import rolling_percentile

SMART_MONEY_MART_NAME = "smart_money_daily"

#: 国家队主体关键词（排除过于宽泛的"中金"以避免券商误报）
NAT_TEAM_KEYWORDS = ("中央汇金", "汇金", "中国证券金融", "证金", "社保基金", "梧桐树")


def _empty_score(calendar: pl.DataFrame, column: str) -> pl.DataFrame:
    return calendar.select(
        pl.col("trade_date"),
        pl.lit(None, dtype=pl.Float64).alias(column),
    )


def build_smart_money_frame(
    insider: pl.DataFrame,
    block_trade: pl.DataFrame,
    top10_holders: pl.DataFrame,
    calendar: pl.DataFrame,
) -> pl.DataFrame:
    """构建聪明钱组合信号日频宽表。

    Args:
        insider: ``insider_activity_daily`` Mart（announcement_date/insider_net_buy_amount）
        block_trade: ``block_trade_daily`` Mart（trade_date/block_trade_amount/...折价率）
        top10_holders: ``top10_floatholders`` 事实表（ann_date/holder_name/hold_change）
        calendar: 交易日历（trade_date, 升序）

    Returns:
        ``trade_date / insider_score / block_score / nat_score / smart_money_score``
    """
    # 1) 产业资本增持
    if insider.is_empty() or "insider_net_buy_amount" not in insider.columns:
        insider_score = _empty_score(calendar, "insider_score")
    else:
        insider_score = (
            calendar.join(
                insider.select(
                    pl.col("announcement_date").cast(pl.Date).alias("trade_date"),
                    pl.col("insider_net_buy_amount").cast(pl.Float64, strict=False),
                ),
                on="trade_date",
                how="left",
            )
            .fill_null(0.0)
            .with_columns(
                pl.col("insider_net_buy_amount").rolling_sum(window_size=20).alias("_net20")
            )
            .with_columns(
                rolling_percentile("_net20", 1250, min_samples=500).alias("insider_score")
            )
            .select(["trade_date", "insider_score"])
        )

    # 2) 大宗折价接盘（折价率中位为负值, 深度 = 金额 × max(0, -折价率)）
    if block_trade.is_empty() or "block_trade_amount" not in block_trade.columns:
        block_score = _empty_score(calendar, "block_score")
    else:
        block_score = (
            calendar.join(
                block_trade.select(
                    "trade_date",
                    pl.col("block_trade_amount").cast(pl.Float64, strict=False),
                    pl.col("block_trade_discount_rate_median").cast(pl.Float64, strict=False),
                ),
                on="trade_date",
                how="left",
            )
            .with_columns(pl.col("block_trade_amount").fill_null(0.0))
            .with_columns(
                pl.when(pl.col("block_trade_discount_rate_median").is_not_null())
                .then(
                    pl.col("block_trade_amount")
                    * (-pl.col("block_trade_discount_rate_median")).clip(lower_bound=0.0)
                )
                .otherwise(None)
                .alias("_disc_depth")
            )
            .with_columns(
                rolling_percentile("_disc_depth", 250, min_samples=60).alias("block_score")
            )
            .select(["trade_date", "block_score"])
        )

    # 3) 国家队股东锚点
    if top10_holders.is_empty() or "hold_change" not in top10_holders.columns:
        nat_score = _empty_score(calendar, "nat_score")
    else:
        mask = pl.Series([False] * len(top10_holders))
        for kw in NAT_TEAM_KEYWORDS:
            mask = mask | top10_holders["holder_name"].str.contains(kw, literal=True)
        agg = (
            top10_holders.filter(mask & pl.col("hold_change").is_not_null())
            .group_by("ann_date")
            .agg(pl.col("hold_change").sum().alias("net_change"))
            .with_columns(pl.col("ann_date").cast(pl.Date))
            .sort("ann_date")
        )
        nat_score = (
            calendar.join_asof(agg, left_on="trade_date", right_on="ann_date", strategy="backward")
            .with_columns(rolling_percentile("net_change", 500, min_samples=20).alias("nat_score"))
            .select(["trade_date", "nat_score"])
        )

    return (
        calendar.join(insider_score, on="trade_date", how="left")
        .join(block_score, on="trade_date", how="left")
        .join(nat_score, on="trade_date", how="left")
        .with_columns(
            pl.mean_horizontal(["insider_score", "block_score", "nat_score"]).alias(
                "smart_money_score"
            )
        )
        .sort("trade_date")
    )


__all__ = ["NAT_TEAM_KEYWORDS", "SMART_MONEY_MART_NAME", "build_smart_money_frame"]
