"""有色大宗金属价格与显性库存 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import NonFerrousMetalsRecord

NON_FERROUS_METALS_SCHEMA = {
    "report_date": pl.String,
    "trade_date": pl.Date,
    "lithium_carbonate_price": pl.Float64,
    "shfe_copper_price": pl.Float64,
    "shfe_aluminum_price": pl.Float64,
    "sge_gold_price": pl.Float64,
    "copper_inventory_ton": pl.Float64,
    "copper_ma200_bias": pl.Float64,
    "copper_mom20": pl.Float64,
    "copper_chg60": pl.Float64,
    "lithium_mom20": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_non_ferrous_metals() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=NON_FERROUS_METALS_SCHEMA)


def records_to_metals_frame(records: Sequence[NonFerrousMetalsRecord]) -> pl.DataFrame:
    """将有色金属记录转换为强类型 Polars DataFrame，并计算 200MA 偏离度与动量指标。"""
    if not records:
        return empty_non_ferrous_metals()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "lithium_carbonate_price": [r.lithium_carbonate_price for r in records],
        "shfe_copper_price": [r.shfe_copper_price for r in records],
        "shfe_aluminum_price": [r.shfe_aluminum_price for r in records],
        "sge_gold_price": [r.sge_gold_price for r in records],
        "copper_inventory_ton": [r.copper_inventory_ton for r in records],
        "copper_ma200_bias": [None] * len(records),
        "copper_mom20": [None] * len(records),
        "copper_chg60": [None] * len(records),
        "lithium_mom20": [None] * len(records),
        "unit": [r.unit or "mixed" for r in records],
        "source": [r.source or "AkShare" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=NON_FERROUS_METALS_SCHEMA)
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )

    # 自动衍生技术偏离度与动量指标
    exprs: list[pl.Expr] = []
    # 铜 200MA 偏离度与动量
    if df["shfe_copper_price"].null_count() < len(df):
        ma200 = pl.col("shfe_copper_price").rolling_mean(window_size=200, min_samples=20)
        exprs.extend(
            [
                ((pl.col("shfe_copper_price") / ma200 - 1.0) * 100.0).alias("copper_ma200_bias"),
                pl.col("shfe_copper_price").log().diff(20).alias("copper_mom20"),
                pl.col("shfe_copper_price").log().diff(60).alias("copper_chg60"),
            ]
        )
    # 碳酸锂 20 日动量
    if df["lithium_carbonate_price"].null_count() < len(df):
        exprs.append(pl.col("lithium_carbonate_price").log().diff(20).alias("lithium_mom20"))

    if exprs:
        df = df.with_columns(exprs)

    return df
