"""航运产业黄金事实表转换。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.shipping.models import ShippingIndicesRecord
from stock_data.fetcher.industry.shipping.schemas import SHIPPING_INDICES_SCHEMA


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

    if df["bdi_ma200_bias"].null_count() == len(df) and "bdi_index" in df.columns:
        bdi_ma200 = pl.col("bdi_index").rolling_mean(window_size=200, min_samples=30)
        df = df.with_columns(
            ((pl.col("bdi_index") / bdi_ma200 - 1.0) * 100.0).alias("bdi_ma200_bias")
        )

    if df["bdti_ma200_bias"].null_count() == len(df) and "bdti_index" in df.columns:
        bdti_ma200 = pl.col("bdti_index").rolling_mean(window_size=200, min_samples=30)
        df = df.with_columns(
            ((pl.col("bdti_index") / bdti_ma200 - 1.0) * 100.0).alias("bdti_ma200_bias")
        )

    return df


__all__ = ["empty_shipping_indices", "records_to_shipping_frame"]
