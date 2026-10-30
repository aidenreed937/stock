"""有色金属产业黄金事实表转换。"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.metals.models import NonFerrousMetalsRecord
from stock_data.fetcher.industry.metals.schemas import NON_FERROUS_METALS_SCHEMA


def empty_non_ferrous_metals() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=NON_FERROUS_METALS_SCHEMA)


def _parse_report_date(value: str | date) -> date:
    """将有色金属报告日期转换为 Curated 的自然日。"""
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def records_to_metals_frame(records: Sequence[NonFerrousMetalsRecord]) -> pl.DataFrame:
    """将有色金属记录转换为强类型 Polars DataFrame，并计算偏离度与动量指标。"""
    if not records:
        return empty_non_ferrous_metals()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [_parse_report_date(r.report_date) for r in records],
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

    exprs: list[pl.Expr] = []
    if df["shfe_copper_price"].null_count() < len(df):
        ma200 = pl.col("shfe_copper_price").rolling_mean(window_size=200, min_samples=20)
        exprs.extend(
            [
                ((pl.col("shfe_copper_price") / ma200 - 1.0) * 100.0).alias("copper_ma200_bias"),
                pl.col("shfe_copper_price").log().diff(20).alias("copper_mom20"),
                pl.col("shfe_copper_price").log().diff(60).alias("copper_chg60"),
            ]
        )
    if df["lithium_carbonate_price"].null_count() < len(df):
        exprs.append(pl.col("lithium_carbonate_price").log().diff(20).alias("lithium_mom20"))

    if exprs:
        df = df.with_columns(exprs)

    return df


__all__ = ["empty_non_ferrous_metals", "records_to_metals_frame"]
