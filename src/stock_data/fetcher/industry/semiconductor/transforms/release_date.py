"""半导体 RAW 发布日期契约。"""

from __future__ import annotations

import polars as pl


def require_raw_release_dates(df: pl.DataFrame, endpoint: str) -> pl.DataFrame:
    """拒绝没有真实源端发布日期的 RAW 行。"""
    if "release_date" not in df.columns:
        raise ValueError(f"半导体 RAW 端点 {endpoint} 缺少 release_date 列")

    missing = df.filter(pl.col("release_date").is_null()).height
    if missing:
        raise ValueError(
            f"半导体 RAW 端点 {endpoint} 有 {missing} 行缺少真实 release_date，拒绝落盘"
        )
    return df
