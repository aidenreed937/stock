"""全球海运与油运日频运价指数 (BDI/BDTI/BCTI/SCFI) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import ShippingIndicesRecord

SHIPPING_INDICES_SCHEMA = {
    "trade_date": pl.Date,
    "bdi_index": pl.Float64,
    "bdti_index": pl.Float64,
    "bcti_index": pl.Float64,
    "scfi_index": pl.Float64,
    "bdi_ma200_bias": pl.Float64,
    "bdti_ma200_bias": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_shipping_indices() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SHIPPING_INDICES_SCHEMA)


def records_to_shipping_frame(records: Sequence[ShippingIndicesRecord]) -> pl.DataFrame:
    """将航运日频运价记录转换为强类型 Polars DataFrame，并自动计算 MA200 偏离度。"""
    if not records:
        return empty_shipping_indices()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "trade_date": [r.trade_date for r in records],
        "bdi_index": [r.bdi_index for r in records],
        "bdti_index": [r.bdti_index for r in records],
        "bcti_index": [r.bcti_index for r in records],
        "scfi_index": [r.scfi_index for r in records],
        "bdi_ma200_bias": [r.bdi_ma200_bias for r in records],
        "bdti_ma200_bias": [r.bdti_ma200_bias for r in records],
        "unit": [r.unit or "index_points" for r in records],
        "source": [r.source or "BalticExchange/SSE" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=SHIPPING_INDICES_SCHEMA)
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )

    # 自动计算 BDI 相对 200 日均线偏离度
    if df["bdi_ma200_bias"].null_count() == len(df) and "bdi_index" in df.columns:
        bdi_ma200 = pl.col("bdi_index").rolling_mean(window_size=200, min_samples=30)
        df = df.with_columns(
            ((pl.col("bdi_index") / bdi_ma200 - 1.0) * 100.0).alias("bdi_ma200_bias")
        )

    # 自动计算 BDTI 相对 200 日均线偏离度
    if df["bdti_ma200_bias"].null_count() == len(df) and "bdti_index" in df.columns:
        bdti_ma200 = pl.col("bdti_index").rolling_mean(window_size=200, min_samples=30)
        df = df.with_columns(
            ((pl.col("bdti_index") / bdti_ma200 - 1.0) * 100.0).alias("bdti_ma200_bias")
        )

    return df
