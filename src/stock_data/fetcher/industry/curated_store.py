"""垂直产业 Curated 黄金事实表写入边界。"""

from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.common import save_curated_fact


def save_curated_dataset(
    df: pl.DataFrame,
    target_path: Path,
    primary_keys: list[str] | None,
) -> int:
    """保存单个产业端点的 Curated 黄金事实表。"""
    return save_curated_fact(df, target_path, primary_keys=primary_keys)
