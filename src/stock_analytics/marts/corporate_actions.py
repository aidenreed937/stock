"""产业资本与公司行为领域 Mart。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

INSIDER_MART_NAME = "insider_activity_daily"
REPURCHASE_MART_NAME = "repurchase_daily"
BLOCK_TRADE_MART_NAME = "block_trade_daily"


def _empty(schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _symbol_column(frame: pl.DataFrame) -> str | None:
    return next((column for column in ("symbol", "ts_code") if column in frame.columns), None)


def _event_date(frame: pl.DataFrame, column: str) -> pl.DataFrame:
    if column not in frame.columns:
        return frame
    return frame.with_columns(parse_mixed_date(column).alias(column)).drop_nulls(subset=[column])


def build_insider_activity_mart(holdertrade: pl.DataFrame) -> pl.DataFrame:
    """按公告日聚合股东及董监高增减持事件。

    净增持金额按 ``change_vol * avg_price`` 估算；缺少均价的记录仍计入事件数，
    但不计入金额，避免把缺失金额当作零值事实。
    """
    schema = {
        "announcement_date": pl.Date,
        "insider_buy_amount": pl.Float64,
        "insider_sell_amount": pl.Float64,
        "insider_net_buy_amount": pl.Float64,
        "insider_buy_event_count": pl.Int64,
        "insider_sell_event_count": pl.Int64,
        "insider_event_count": pl.Int64,
    }
    required = {"ann_date", "in_de", "change_vol"}
    if holdertrade.is_empty() or not required.issubset(holdertrade.columns):
        return _empty(schema)

    frame = _event_date(holdertrade, "ann_date").with_columns(
        pl.col("change_vol").cast(pl.Float64, strict=False).abs().alias("_change_vol"),
        pl.col("in_de").cast(pl.Utf8, strict=False).str.to_uppercase().alias("_direction"),
    )
    if "avg_price" in frame.columns:
        frame = frame.with_columns(
            (pl.col("_change_vol") * pl.col("avg_price").cast(pl.Float64, strict=False)).alias(
                "_amount"
            )
        )
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("_amount"))

    is_buy = pl.col("_direction").is_in(["IN", "BUY", "增持"])
    is_sell = pl.col("_direction").is_in(["DE", "SELL", "减持", "OUT"])
    result = frame.group_by("ann_date").agg(
        pl.when(is_buy).then(pl.col("_amount")).otherwise(None).sum().alias("insider_buy_amount"),
        pl.when(is_sell).then(pl.col("_amount")).otherwise(None).sum().alias("insider_sell_amount"),
        is_buy.sum().cast(pl.Int64).alias("insider_buy_event_count"),
        is_sell.sum().cast(pl.Int64).alias("insider_sell_event_count"),
        pl.len().cast(pl.Int64).alias("insider_event_count"),
    )
    return (
        result.with_columns(
            (pl.col("insider_buy_amount") - pl.col("insider_sell_amount")).alias(
                "insider_net_buy_amount"
            ),
            pl.col("ann_date").alias("announcement_date"),
        )
        .drop("ann_date")
        .select(list(schema))
        .sort("announcement_date")
    )


def build_repurchase_mart(repurchase: pl.DataFrame) -> pl.DataFrame:
    """按公告日聚合回购公告与实施状态。"""
    schema = {
        "announcement_date": pl.Date,
        "repurchase_announcement_count": pl.Int64,
        "repurchase_implemented_count": pl.Int64,
        "repurchase_volume": pl.Float64,
        "repurchase_amount": pl.Float64,
    }
    required = {"ann_date", "proc"}
    if repurchase.is_empty() or not required.issubset(repurchase.columns):
        return _empty(schema)

    frame = _event_date(repurchase, "ann_date").with_columns(
        pl.col("proc").cast(pl.Utf8, strict=False).fill_null("").alias("_proc")
    )
    implemented = pl.col("_proc").str.contains("完成|实施", literal=False)
    aggregates: list[pl.Expr] = [
        pl.len().cast(pl.Int64).alias("repurchase_announcement_count"),
        implemented.sum().cast(pl.Int64).alias("repurchase_implemented_count"),
    ]
    for source, target in (("vol", "repurchase_volume"), ("amount", "repurchase_amount")):
        if source in frame.columns:
            aggregates.append(pl.col(source).cast(pl.Float64, strict=False).sum().alias(target))
        else:
            aggregates.append(pl.lit(None, dtype=pl.Float64).alias(target))
    return (
        frame.group_by("ann_date")
        .agg(aggregates)
        .rename({"ann_date": "announcement_date"})
        .select(list(schema))
        .sort("announcement_date")
    )


def build_block_trade_mart(
    block_trade: pl.DataFrame,
    daily_bars: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """按交易日聚合大宗交易金额，并可选计算相对收盘价折溢价。

    ``discount_rate`` 采用 ``成交价 / 当日收盘价 - 1``，因此折价为负值；
    未提供行情收盘价时，该列保持为空而不是用交易价替代。
    """
    schema = {
        "trade_date": pl.Date,
        "block_trade_event_count": pl.Int64,
        "block_trade_volume": pl.Float64,
        "block_trade_amount": pl.Float64,
        "block_trade_discount_rate_median": pl.Float64,
    }
    volume_column = "volume" if "volume" in block_trade.columns else "vol"
    required = {"trade_date", "price", volume_column, "amount"}
    if block_trade.is_empty() or not required.issubset(block_trade.columns):
        return _empty(schema)

    frame = _event_date(block_trade, "trade_date").with_columns(
        pl.col("price").cast(pl.Float64, strict=False).alias("_price"),
        pl.col(volume_column).cast(pl.Float64, strict=False).alias("_volume"),
        pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
    )
    symbol = _symbol_column(frame)
    if daily_bars is not None and symbol is not None:
        bar_symbol = _symbol_column(daily_bars)
        if bar_symbol is not None and {"trade_date", "close"}.issubset(daily_bars.columns):
            bars = (
                _event_date(daily_bars, "trade_date")
                .select(
                    pl.col(bar_symbol).cast(pl.Utf8).alias("_bar_symbol"),
                    "trade_date",
                    pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
                )
                .unique(subset=["_bar_symbol", "trade_date"], keep="last")
            )
            frame = (
                frame.with_columns(pl.col(symbol).cast(pl.Utf8).alias("_bar_symbol"))
                .join(bars, on=["_bar_symbol", "trade_date"], how="left")
                .with_columns(
                    pl.when((pl.col("_close") > 0) & pl.col("_price").is_not_null())
                    .then(pl.col("_price") / pl.col("_close") - 1.0)
                    .otherwise(None)
                    .alias("_discount_rate")
                )
            )
    if "_discount_rate" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("_discount_rate"))

    return (
        frame.group_by("trade_date")
        .agg(
            pl.len().cast(pl.Int64).alias("block_trade_event_count"),
            pl.col("_volume").sum().alias("block_trade_volume"),
            pl.col("_amount").sum().alias("block_trade_amount"),
            pl.col("_discount_rate").median().alias("block_trade_discount_rate_median"),
        )
        .select(list(schema))
        .sort("trade_date")
    )


__all__ = [
    "BLOCK_TRADE_MART_NAME",
    "INSIDER_MART_NAME",
    "REPURCHASE_MART_NAME",
    "build_block_trade_mart",
    "build_insider_activity_mart",
    "build_repurchase_mart",
]
