"""期货主力连续日度行情 RAW/Curated 转换。"""

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_FUTURES_DAILY_RAW_SCHEMA,
    CHEMICAL_FUTURES_DAILY_SCHEMA,
)


def build_futures_daily_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """将采集结果转换为源值文本优先的 RAW 表。"""
    if df.is_empty():
        return pl.DataFrame(schema=CHEMICAL_FUTURES_DAILY_RAW_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    exprs = []
    for col, dtype in CHEMICAL_FUTURES_DAILY_RAW_SCHEMA.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype))
        elif col.endswith("_raw"):
            base_col = col[:-4]
            if base_col in df.columns:
                exprs.append(pl.col(base_col).cast(pl.String).alias(col))
            else:
                exprs.append(pl.lit(None, dtype=dtype).alias(col))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col))
    return (
        df.select(exprs)
        .unique(subset=["symbol", "contract", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
    )


def build_futures_daily_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从 RAW 源值文本恢复标准化期货日度行情事实表。"""
    if df.is_empty():
        return pl.DataFrame(schema=CHEMICAL_FUTURES_DAILY_SCHEMA)
    exprs = []
    for col, dtype in CHEMICAL_FUTURES_DAILY_SCHEMA.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype, strict=False))
        else:
            raw_col = f"{col}_raw"
            if raw_col in df.columns:
                exprs.append(pl.col(raw_col).cast(dtype, strict=False).alias(col))
            else:
                exprs.append(pl.lit(None, dtype=dtype).alias(col))
    return (
        df.select(exprs)
        .unique(subset=["symbol", "contract", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
    )


build_futures_price_curated_frame = build_futures_daily_curated_frame
build_futures_price_raw_frame = build_futures_daily_raw_frame


__all__ = [
    "build_futures_daily_curated_frame",
    "build_futures_daily_raw_frame",
    "build_futures_price_curated_frame",
    "build_futures_price_raw_frame",
]
