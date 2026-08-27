"""龙虎榜与机构/游资席位日频领域 Mart。

将 230 万行 ``top_inst`` 席位明细与 18.8 万行 ``top_list`` 逐日聚合为数千行日频
事实，供短线情绪与机构博弈分析直接消费，避免下游重复扫描明细表。

口径说明：
- ``top_inst.side``：1 = 买入，0 = 卖出；
- 机构席位按 ``exalter`` 匹配 ``机构专用 / 沪股通 / 深股通 / 中小投资者``；
- 游资净买入为"知名游资席位"关键词匹配的估算值，仅作情绪代理，不精确定义；
- ``market_amount`` 取 ``FeatureStore.market_daily.total_turnover``（全市场 A 股
  日成交额，元），``top_list_turnover_share`` = 龙虎榜成交总额 / 全市场成交额（%）。
"""

from __future__ import annotations

from typing import Any

import polars as pl

DRAGON_TIGER_MART_NAME = "dragon_tiger_daily"

#: 龙虎榜机构/通道专用席位关键词
INSTITUTIONAL_SEAT_KEYWORDS = ("机构专用", "沪股通", "深股通", "中小投资者")

#: 知名游资席位关键词（近似识别，仅供情绪代理）
HOT_MONEY_KEYWORDS = (
    "拉萨",
    "宁波桑田路",
    "上海江苏路",
    "深圳蛇口",
    "上海溧阳路",
    "北京中关村",
    "深圳益田路",
    "杭州庆春路",
    "上海建国西路",
    "深圳福华一路",
)

HEAVY_BUY_THRESHOLD = 50_000_000.0  # 机构净买入超 5000 万元即"重仓买入"

DRAGON_TIGER_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "inst_buy_amount": pl.Float64,
    "inst_sell_amount": pl.Float64,
    "inst_net_buy_amount": pl.Float64,
    "inst_active_stock_count": pl.Int64,
    "inst_heavy_buy_count": pl.Int64,
    "hot_money_net_buy_amount": pl.Float64,
    "top_list_issue_count": pl.Int64,
    "top_list_total_amount": pl.Float64,
    "top_list_net_amount": pl.Float64,
    "market_amount": pl.Float64,
    "top_list_turnover_share": pl.Float64,
}


def empty_dragon_tiger() -> pl.DataFrame:
    """返回稳定 schema 的空龙虎榜 Mart。"""
    return pl.DataFrame(schema=DRAGON_TIGER_SCHEMA)


def _is_institutional(seat: pl.Expr) -> pl.Expr:
    """机构/通道席位布尔标记。"""
    return pl.any_horizontal(
        [pl.col("exalter").str.contains(kw, literal=True) for kw in INSTITUTIONAL_SEAT_KEYWORDS]
    )


def _is_hot_money(seat: pl.Expr) -> pl.Expr:
    return pl.any_horizontal(
        [pl.col("exalter").str.contains(kw, literal=True) for kw in HOT_MONEY_KEYWORDS]
    )


def build_dragon_tiger_frame(
    top_inst: pl.DataFrame,
    top_list: pl.DataFrame,
    market_turnover: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从龙虎榜明细构建日频聚合。

    ``market_turnover`` 为 (trade_date, market_amount) 全市场日成交额（元），
    用于计算龙虎榜成交占全市场成交额比例；缺省时占比保持缺失。
    """
    schema = DRAGON_TIGER_SCHEMA
    required = {"trade_date", "exalter", "side", "buy", "sell", "net_buy"}
    if top_inst.is_empty() or not required.issubset(top_inst.columns):
        return empty_dragon_tiger()

    inst = top_inst.with_columns(
        _is_institutional(pl.col("exalter")).alias("_is_inst"),
        _is_hot_money(pl.col("exalter")).alias("_is_hot"),
        pl.col("buy").cast(pl.Float64, strict=False).fill_null(0.0).alias("_buy"),
        pl.col("sell").cast(pl.Float64, strict=False).fill_null(0.0).alias("_sell"),
        pl.col("net_buy").cast(pl.Float64, strict=False).fill_null(0.0).alias("_net_buy"),
        pl.col("side").cast(pl.Utf8, strict=False).alias("_side"),
    )

    # 机构口径：机构专用 + 沪股通/深股通通道 + 中小投资者（龙虎榜"机构"公开口径）
    inst_seats = inst.filter(pl.col("_is_inst"))
    daily = (
        inst_seats.group_by("trade_date")
        .agg(
            pl.col("_buy").sum().alias("inst_buy_amount"),
            pl.col("_sell").sum().alias("inst_sell_amount"),
            pl.col("symbol").n_unique().alias("inst_active_stock_count"),
        )
        .with_columns(
            (pl.col("inst_buy_amount") - pl.col("inst_sell_amount")).alias("inst_net_buy_amount"),
        )
    )

    heavy = (
        inst_seats.group_by("trade_date", "symbol")
        .agg(pl.col("_net_buy").sum().alias("_stock_net_buy"))
        .filter(pl.col("_stock_net_buy") >= HEAVY_BUY_THRESHOLD)
        .group_by("trade_date")
        .agg(pl.len().cast(pl.Int64).alias("inst_heavy_buy_count"))
    )
    # 游资口径独立于机构口径（席位类型互斥），避免被机构过滤误伤
    hot = (
        inst.filter(pl.col("_is_hot"))
        .group_by("trade_date")
        .agg(pl.col("_net_buy").sum().alias("hot_money_net_buy_amount"))
    )

    stock_count: list[pl.Expr] = [
        pl.len().cast(pl.Int64).alias("top_list_issue_count"),
        pl.col("amount").cast(pl.Float64, strict=False).sum().alias("top_list_total_amount"),
        pl.col("net_amount").cast(pl.Float64, strict=False).sum().alias("top_list_net_amount"),
    ]
    top_daily = (
        top_list.group_by("trade_date")
        .agg(stock_count)
        .with_columns(
            pl.col("top_list_total_amount").fill_null(0.0),
            pl.col("top_list_net_amount").fill_null(0.0),
        )
    )

    result = daily.join(heavy, on="trade_date", how="left").join(hot, on="trade_date", how="left")
    if not top_daily.is_empty():
        result = result.join(top_daily, on="trade_date", how="left")
    else:
        result = result.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("top_list_issue_count"),
            pl.lit(None, dtype=pl.Float64).alias("top_list_total_amount"),
            pl.lit(None, dtype=pl.Float64).alias("top_list_net_amount"),
        )

    if market_turnover is not None and not market_turnover.is_empty():
        turnover = (
            market_turnover.select(
                "trade_date",
                pl.col("market_amount").cast(pl.Float64, strict=False),
            )
            .unique(subset=["trade_date"], keep="last")
            .sort("trade_date")
        )
        result = result.join(turnover, on="trade_date", how="left").with_columns(
            pl.when(pl.col("market_amount") > 0)
            .then(pl.col("top_list_total_amount") / pl.col("market_amount") * 100.0)
            .otherwise(None)
            .alias("top_list_turnover_share"),
        )
    else:
        result = result.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("market_amount"),
            pl.lit(None, dtype=pl.Float64).alias("top_list_turnover_share"),
        )

    return result.select(list(schema)).sort("trade_date")


__all__ = ["DRAGON_TIGER_MART_NAME", "build_dragon_tiger_frame", "empty_dragon_tiger"]
