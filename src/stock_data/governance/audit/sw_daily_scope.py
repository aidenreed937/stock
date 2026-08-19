"""申万行业日行情审计范围筛选。"""

from __future__ import annotations

from math import ceil
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_data.governance.audit.benchmarks.industry import IndustryDailyBenchmarkProvider


def filter_sw_daily_scope(
    df: pl.DataFrame,
    base_dir: Path,
) -> tuple[pl.DataFrame, str | None]:
    """将 sw_daily 审计限定为 SW2021 一级行业，避免跨层级均值混算。"""
    if {"classification", "industry_level"}.issubset(df.columns):
        issue: str | None = None
        if "classification_status" in df.columns:
            legacy_count = df.filter(pl.col("classification_status").is_null()).height
            bad_mapped_count = df.filter(
                (pl.col("classification_status") == "mapped")
                & (pl.col("classification").is_null() | pl.col("industry_level").is_null())
            ).height
            if legacy_count or bad_mapped_count:
                issue = (
                    f"SW2021 分类尚未完整物化: legacy_null_status={legacy_count}, "
                    f"bad_mapped_rows={bad_mapped_count}"
                )
        scoped = df.filter(
            (pl.col("classification") == "SW2021") & (pl.col("industry_level") == "L1")
        )
        if not scoped.is_empty() and "symbol" in scoped.columns:
            coverage = scoped.group_by("trade_date").agg(
                pl.col("symbol").n_unique().alias("l1_symbol_count")
            )
            max_coverage = coverage["l1_symbol_count"].max()
            if isinstance(max_coverage, int | float) and max_coverage >= 10:
                min_coverage = max(1, ceil(float(max_coverage) * 0.8))
                eligible_dates = coverage.filter(pl.col("l1_symbol_count") >= min_coverage).select(
                    "trade_date"
                )
                excluded_dates = len(coverage) - len(eligible_dates)
                if excluded_dates:
                    logger.info(
                        "sw_daily L1 分布审计过滤低覆盖交易日: "
                        f"{excluded_dates} 个交易日, 要求至少 {min_coverage}/{max_coverage} 个行业"
                    )
                    scoped = scoped.join(eligible_dates, on="trade_date", how="inner")
        return scoped, issue
    if "classification" in df.columns or "industry_level" in df.columns:
        return df.head(0), "SW2021 分类列不完整，拒绝按混合口径审计"

    try:
        catalog = DataCatalog(data_source="tushare", storage_dir=base_dir)
        codes = IndustryDailyBenchmarkProvider(
            catalog=catalog,
            data_source="tushare",
            level="L1",
        )._get_industry_codes()
    except Exception as exc:
        logger.debug(f"读取 SW2021 一级行业范围失败，审计按空集处理: {exc}")
        return df.head(0), "无法读取 SW2021 一级行业字典，拒绝按混合口径审计"
    return (
        (
            df.filter(pl.col("symbol").cast(pl.String).is_in(codes)),
            None,
        )
        if "symbol" in df.columns
        else (df.head(0), "sw_daily 缺少 symbol 主键")
    )
