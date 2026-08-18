"""历史 Curated 字段兼容处理。"""

import polars as pl


def normalize_legacy_index_valuation(df: pl.DataFrame) -> pl.DataFrame:
    """将旧版 total_assets 别名归一到当前 index_valuation 字段。"""
    if "total_assets" not in df.columns:
        return df
    if "market_cap" not in df.columns:
        return df.rename({"total_assets": "market_cap"})
    return df.with_columns(
        pl.coalesce(
            [pl.col("market_cap").cast(pl.Float64, strict=False), pl.col("total_assets")]
        ).alias("market_cap")
    ).drop("total_assets")
