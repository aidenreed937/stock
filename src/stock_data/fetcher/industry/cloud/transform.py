"""云厂商季度 CapEx 的 RAW/Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl

from stock_data.fetcher.industry.cloud.models import CloudCapexRecord
from stock_data.fetcher.industry.cloud.schemas import (
    CLOUD_CAPEX_CURATED_SCHEMA,
    CLOUD_CAPEX_RAW_SCHEMA,
    CLOUD_CAPEX_SCHEMA,
)

_COMPONENTS = (
    ("msft_capex_raw", "msft_capex_billion_usd"),
    ("goog_capex_raw", "goog_capex_billion_usd"),
    ("meta_capex_raw", "meta_capex_billion_usd"),
    ("amzn_capex_raw", "amzn_capex_billion_usd"),
)
_COMPONENT_RELEASE_DATES = (
    "msft_release_date",
    "goog_release_date",
    "meta_release_date",
    "amzn_release_date",
)


def empty_raw_cloud_capex() -> pl.DataFrame:
    """构造云 CapEx RAW 空事实表骨架。"""
    return pl.DataFrame(schema=CLOUD_CAPEX_RAW_SCHEMA)


def empty_cloud_capex() -> pl.DataFrame:
    """构造云 CapEx Curated 空事实表骨架。"""
    return pl.DataFrame(schema=CLOUD_CAPEX_CURATED_SCHEMA)


def records_to_raw_cloud_capex_frame(
    records: Sequence[CloudCapexRecord],
) -> pl.DataFrame:
    """将云 CapEx 记录转换为只含源端字段和血缘的 RAW 帧。"""
    if not records:
        return empty_raw_cloud_capex()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_quarter": [record.report_quarter for record in records],
        "trade_date": [record.trade_date for record in records],
        "msft_capex_raw": [
            _raw_value(record.msft_capex_raw, record.msft_capex_billion_usd) for record in records
        ],
        "goog_capex_raw": [
            _raw_value(record.goog_capex_raw, record.goog_capex_billion_usd) for record in records
        ],
        "meta_capex_raw": [
            _raw_value(record.meta_capex_raw, record.meta_capex_billion_usd) for record in records
        ],
        "amzn_capex_raw": [
            _raw_value(record.amzn_capex_raw, record.amzn_capex_billion_usd) for record in records
        ],
        "msft_release_date": [
            record.msft_release_date or record.release_date for record in records
        ],
        "goog_release_date": [
            record.goog_release_date or record.release_date for record in records
        ],
        "meta_release_date": [
            record.meta_release_date or record.release_date for record in records
        ],
        "amzn_release_date": [
            record.amzn_release_date or record.release_date for record in records
        ],
        "unit": [record.unit or "billion_usd" for record in records],
        "source": [record.source or "SEC_EDGAR_10Q" for record in records],
        "source_url": [record.source_url or "https://www.sec.gov/edgar/" for record in records],
        "data_status": [record.data_status or "actual" for record in records],
        "collected_at": [record.collected_at or now_iso for record in records],
        "raw_content_sha256": [record.raw_content_sha256 for record in records],
        "raw_snapshot_path": [record.raw_snapshot_path for record in records],
    }
    return (
        pl.DataFrame(data, schema=CLOUD_CAPEX_RAW_SCHEMA)
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )


def build_cloud_capex_raw_frame(
    raw_rows: pl.DataFrame | Sequence[CloudCapexRecord],
) -> pl.DataFrame:
    """整理云 CapEx RAW 帧，兼容旧 Curated 数值列但不保留派生列。"""
    if not isinstance(raw_rows, pl.DataFrame):
        return records_to_raw_cloud_capex_frame(raw_rows)
    if raw_rows.is_empty():
        return empty_raw_cloud_capex()

    df = raw_rows
    additions: list[pl.Expr] = []
    for raw_column, numeric_column in _COMPONENTS:
        if raw_column not in df.columns:
            if numeric_column in df.columns:
                additions.append(pl.col(numeric_column).cast(pl.String).alias(raw_column))
            else:
                additions.append(pl.lit(None, dtype=pl.String).alias(raw_column))
    for release_column in _COMPONENT_RELEASE_DATES:
        if release_column not in df.columns:
            if "release_date" in df.columns:
                additions.append(pl.col("release_date").cast(pl.Date).alias(release_column))
            else:
                additions.append(pl.lit(None, dtype=pl.Date).alias(release_column))
    defaults: dict[str, tuple[Any, object]] = {
        "unit": (pl.String, "billion_usd"),
        "source": (pl.String, "SEC_EDGAR_10Q"),
        "source_url": (pl.String, "https://www.sec.gov/edgar/"),
        "data_status": (pl.String, "actual"),
        "collected_at": (pl.String, ""),
        "raw_content_sha256": (pl.String, ""),
        "raw_snapshot_path": (pl.String, ""),
    }
    for column, (dtype, value) in defaults.items():
        if column not in df.columns:
            additions.append(pl.lit(value, dtype=dtype).alias(column))
    if additions:
        df = df.with_columns(additions)

    return (
        df.select(list(CLOUD_CAPEX_RAW_SCHEMA))
        .with_columns(
            [
                pl.col(name).cast(dtype, strict=False).alias(name)
                for name, dtype in CLOUD_CAPEX_RAW_SCHEMA.items()
            ]
        )
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )


def build_cloud_capex_curated_frame(
    raw_rows: pl.DataFrame | Sequence[CloudCapexRecord],
) -> pl.DataFrame:
    """从云 CapEx RAW 字段计算合计、同比、环比和合成生效日。"""
    df_raw = build_cloud_capex_raw_frame(raw_rows)
    if df_raw.is_empty():
        return empty_cloud_capex()

    component_exprs = [
        _numeric_expr(raw_column).alias(numeric_column)
        for raw_column, numeric_column in _COMPONENTS
    ]
    df = df_raw.with_columns(component_exprs)
    component_columns = [numeric_column for _, numeric_column in _COMPONENTS]
    complete = pl.all_horizontal(
        [pl.col(column).is_not_null() & (pl.col(column) > 0) for column in component_columns]
    )
    release_complete = pl.all_horizontal(
        [pl.col(column).is_not_null() for column in _COMPONENT_RELEASE_DATES]
    )
    df = df.with_columns(
        pl.when(complete)
        .then(pl.sum_horizontal(component_columns).round(3))
        .otherwise(None)
        .alias("total_capex_billion_usd"),
        pl.when(complete & release_complete)
        .then(pl.max_horizontal(_COMPONENT_RELEASE_DATES))
        .otherwise(None)
        .alias("release_date"),
    ).sort("trade_date")
    df = df.with_columns(
        (
            pl.col("total_capex_billion_usd") / pl.col("total_capex_billion_usd").shift(4) - 1.0
        ).alias("yoy_growth"),
        (
            pl.col("total_capex_billion_usd") / pl.col("total_capex_billion_usd").shift(1) - 1.0
        ).alias("qoq_growth"),
    )
    return df.select(list(CLOUD_CAPEX_CURATED_SCHEMA))


def records_to_cloud_capex_frame(records: Sequence[CloudCapexRecord]) -> pl.DataFrame:
    """兼容旧调用方：将记录转换为云 CapEx Curated 帧。"""
    return build_cloud_capex_curated_frame(records)


def _raw_value(raw_value: str | None, numeric_value: float | None) -> str | None:
    if raw_value is not None:
        return raw_value
    return str(numeric_value) if numeric_value is not None else None


def _numeric_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace_all(r"[^\d.eE+-]", "")
        .cast(pl.Float64, strict=False)
    )


__all__ = [
    "CLOUD_CAPEX_CURATED_SCHEMA",
    "CLOUD_CAPEX_RAW_SCHEMA",
    "CLOUD_CAPEX_SCHEMA",
    "build_cloud_capex_curated_frame",
    "build_cloud_capex_raw_frame",
    "empty_cloud_capex",
    "empty_raw_cloud_capex",
    "records_to_cloud_capex_frame",
    "records_to_raw_cloud_capex_frame",
]
