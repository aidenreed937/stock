"""中国创新药海外 License-out (BD) 交易首付款与总额 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import PharmaLicenseOutRecord

PHARMA_LICENSE_OUT_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "monthly_upfront_million_usd": pl.Float64,
    "monthly_total_deal_million_usd": pl.Float64,
    "deal_count": pl.Int64,
    "upfront_3mma": pl.Float64,
    "total_deal_3mma": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_pharma_license_out() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=PHARMA_LICENSE_OUT_SCHEMA)


def records_to_pharma_bd_frame(records: Sequence[PharmaLicenseOutRecord]) -> pl.DataFrame:
    """将创新药海外 BD 授权记录转换为强类型 Polars DataFrame，并自动计算 3MMA 与同比/环比。"""
    if not records:
        return empty_pharma_license_out()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "monthly_upfront_million_usd": [r.monthly_upfront_million_usd for r in records],
        "monthly_total_deal_million_usd": [r.monthly_total_deal_million_usd for r in records],
        "deal_count": [r.deal_count for r in records],
        "upfront_3mma": [r.upfront_3mma for r in records],
        "total_deal_3mma": [None] * len(records),
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "million_usd" for r in records],
        "source": [r.source or "PharmaCube/Announcements" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=PHARMA_LICENSE_OUT_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    # 自动计算首付款 3MMA 与总交易额 3MMA (平滑大单脉冲)
    if df["upfront_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("monthly_upfront_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("upfront_3mma"),
            pl.col("monthly_total_deal_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("total_deal_3mma"),
        )
    else:
        df = df.with_columns(
            pl.col("monthly_total_deal_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("total_deal_3mma")
        )

    # 衍生同比与环比斜率
    if df["yoy_growth_3mma"].null_count() == len(df):
        df = df.with_columns(
            (pl.col("upfront_3mma") / pl.col("upfront_3mma").shift(12) - 1.0).alias(
                "yoy_growth_3mma"
            ),
            (pl.col("upfront_3mma") / pl.col("upfront_3mma").shift(1) - 1.0).alias(
                "mom_growth_3mma"
            ),
        )

    return df
