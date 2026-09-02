"""半导体端点附加执行逻辑。"""

import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def backfill_semiconductor_china(curated_path: Path) -> int:
    """从 SIA raw 新闻重建 China 月度序列并回填 semiconductor_sales 黄金表。"""
    try:
        from stock_data.fetcher.industry.semiconductor.china_series import (
            build_china_series,
            parse_sia_raw_dir,
            save_china_series,
        )

        raw_sia = curated_path.parent.parent / "raw" / "industry" / "sia"
        records = parse_sia_raw_dir(raw_sia)
        if not records:
            return 0
        series = build_china_series(records)
        if series.is_empty():
            return 0
        save_china_series(series, curated_path / "semiconductor_china_series.parquet")
        _merge_semiconductor_china_series(curated_path / "semiconductor_sales.parquet", series)
        filled = int(series["china_sales_usd"].is_not_null().sum())
        logger.info("semiconductor_sales China 回填完成: %d 个月", filled)
        return filled
    except Exception as exc:  # noqa: BLE001
        logger.warning("semiconductor_sales China 回填失败 (非阻塞): %s", exc)
        return 0


def _merge_semiconductor_china_series(sales_path: Path, series: pl.DataFrame) -> None:
    china_map = series.select(
        ["report_month", "china_sales_usd", "china_yoy_growth", "china_mom_growth"]
    ).rename(
        {"china_sales_usd": "_c_sales", "china_yoy_growth": "_c_yoy", "china_mom_growth": "_c_mom"}
    )
    merged = (
        pl.read_parquet(sales_path)
        .join(china_map, on="report_month", how="left")
        .with_columns(
            pl.coalesce([pl.col("_c_sales"), pl.col("china_sales_usd")]).alias("china_sales_usd"),
            pl.coalesce([pl.col("_c_yoy"), pl.col("china_yoy_growth")]).alias("china_yoy_growth"),
            pl.coalesce([pl.col("_c_mom"), pl.col("china_mom_growth")]).alias("china_mom_growth"),
        )
        .drop(["_c_sales", "_c_yoy", "_c_mom"])
    )
    merged.write_parquet(sales_path)
