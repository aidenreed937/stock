"""海关总署 (GACC) 变压器出口金额、数量与均价 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import TransformerExportRecord

TRANSFORMER_EXPORT_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "export_value_million_usd": pl.Float64,
    "export_volume_units": pl.Float64,
    "export_asp_usd": pl.Float64,
    "export_value_3mma": pl.Float64,
    "yoy_growth": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_transformer_export() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=TRANSFORMER_EXPORT_SCHEMA)


def records_to_transformer_frame(records: Sequence[TransformerExportRecord]) -> pl.DataFrame:
    """将海关变压器出口记录转换为强类型 Polars DataFrame，并自动计算 3MMA 与同比/环比。"""
    if not records:
        return empty_transformer_export()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "export_value_million_usd": [r.export_value_million_usd for r in records],
        "export_volume_units": [r.export_volume_units for r in records],
        "export_asp_usd": [r.export_asp_usd for r in records],
        "export_value_3mma": [r.export_value_3mma for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "million_usd" for r in records],
        "source": [r.source or "GACC" for r in records],
        "source_url": [r.source_url or "http://stats.customs.gov.cn/" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=TRANSFORMER_EXPORT_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    # 若记录中未显式传入 3MMA，自动进行滚动平滑与斜率补全
    if df["export_value_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("export_value_million_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("export_value_3mma")
        )

    # 衍生同比与环比斜率
    if df["yoy_growth"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.col("export_value_million_usd") / pl.col("export_value_million_usd").shift(12)
                - 1.0
            ).alias("yoy_growth")
        )

    if df["yoy_growth_3mma"].null_count() == len(df):
        df = df.with_columns(
            (pl.col("export_value_3mma") / pl.col("export_value_3mma").shift(12) - 1.0).alias(
                "yoy_growth_3mma"
            ),
            (pl.col("export_value_3mma") / pl.col("export_value_3mma").shift(1) - 1.0).alias(
                "mom_growth_3mma"
            ),
        )

    # 若有数量与金额，补全 ASP
    if df["export_asp_usd"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.when(
                    (pl.col("export_volume_units").is_not_null())
                    & (pl.col("export_volume_units") > 0)
                )
                .then(
                    pl.col("export_value_million_usd") * 1_000_000.0 / pl.col("export_volume_units")
                )
                .otherwise(None)
            ).alias("export_asp_usd")
        )

    return df
