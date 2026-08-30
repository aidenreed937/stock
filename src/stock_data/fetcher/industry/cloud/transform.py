"""北美四大云厂商 (CSP) 季度 AI 资本开支 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import CloudCapexRecord

CLOUD_CAPEX_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "total_capex_billion_usd": pl.Float64,
    "msft_capex_billion_usd": pl.Float64,
    "goog_capex_billion_usd": pl.Float64,
    "meta_capex_billion_usd": pl.Float64,
    "amzn_capex_billion_usd": pl.Float64,
    "yoy_growth": pl.Float64,
    "qoq_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_cloud_capex() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=CLOUD_CAPEX_SCHEMA)


def records_to_cloud_capex_frame(records: Sequence[CloudCapexRecord]) -> pl.DataFrame:
    """将云厂商季度 CapEx 记录转换为强类型 Polars DataFrame，并自动补全同比与环比。"""
    if not records:
        return empty_cloud_capex()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_quarter": [r.report_quarter for r in records],
        "trade_date": [r.trade_date for r in records],
        "total_capex_billion_usd": [r.total_capex_billion_usd for r in records],
        "msft_capex_billion_usd": [r.msft_capex_billion_usd for r in records],
        "goog_capex_billion_usd": [r.goog_capex_billion_usd for r in records],
        "meta_capex_billion_usd": [r.meta_capex_billion_usd for r in records],
        "amzn_capex_billion_usd": [r.amzn_capex_billion_usd for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "qoq_growth": [r.qoq_growth for r in records],
        "unit": [r.unit or "billion_usd" for r in records],
        "source": [r.source or "Company Filings (10-Q/10-K)" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=CLOUD_CAPEX_SCHEMA)
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )

    # 自动补全同比 (shift 4) 与环比 (shift 1)
    if df["yoy_growth"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.col("total_capex_billion_usd") / pl.col("total_capex_billion_usd").shift(4) - 1.0
            ).alias("yoy_growth")
        )

    if df["qoq_growth"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.col("total_capex_billion_usd") / pl.col("total_capex_billion_usd").shift(1) - 1.0
            ).alias("qoq_growth")
        )

    return df
