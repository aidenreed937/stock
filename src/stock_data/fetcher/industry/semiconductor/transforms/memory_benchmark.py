"""TrendForce DataTrack 内存现货月度基准价格 Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.datatrack_calendar import (
    load_datatrack_release_calendar,
)
from stock_data.fetcher.industry.semiconductor.models import MemoryPriceBenchmarkRecord
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)

MEMORY_BENCHMARK_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "product_family": pl.String,
    "indicator_id_raw": pl.String,
    "indicator_name_raw": pl.String,
    "period_raw": pl.String,
    "value_raw": pl.String,
    "freq_raw": pl.String,
    "unit_raw": pl.String,
    "data_source_raw": pl.String,
    "inferenced_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "release_date_raw": pl.String,
    "release_date_status": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

MEMORY_BENCHMARK_CURATED_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "product_family": pl.String,
    "indicator_id": pl.Int64,
    "indicator_name": pl.String,
    "price_usd": pl.Float64,
    "price_mom": pl.Float64,
    "price_yoy": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "release_date_status": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_raw_memory_benchmark() -> pl.DataFrame:
    """构造内存基准价格 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=MEMORY_BENCHMARK_RAW_SCHEMA)


def records_to_raw_memory_benchmark_frame(
    records: Sequence[MemoryPriceBenchmarkRecord],
) -> pl.DataFrame:
    """将 DataTrack 内存基准价格记录转换为纯源端字段与原始值的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_memory_benchmark()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "product_family": [r.product_family for r in records],
        "indicator_id_raw": [r.indicator_id_raw for r in records],
        "indicator_name_raw": [r.indicator_name_raw for r in records],
        "period_raw": [r.period_raw for r in records],
        "value_raw": [r.value_raw for r in records],
        "freq_raw": [r.freq_raw for r in records],
        "unit_raw": [r.unit_raw for r in records],
        "data_source_raw": [r.data_source_raw for r in records],
        "inferenced_raw": [r.inferenced_raw for r in records],
        "source": [r.source or "TrendForce" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "release_date_raw": [r.release_date_raw for r in records],
        "release_date_status": [r.release_date_status for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=MEMORY_BENCHMARK_RAW_SCHEMA)
            .unique(subset=["report_month", "product_family", "indicator_id_raw"], keep="last")
            .sort(["product_family", "indicator_id_raw", "trade_date"])
        ),
        "semiconductor_memory_benchmark",
        allow_unavailable=True,
    )


def empty_memory_benchmark() -> pl.DataFrame:
    """构造内存基准价格 Curated 空事实表骨架。"""
    return pl.DataFrame(schema=MEMORY_BENCHMARK_CURATED_SCHEMA)


def records_to_memory_benchmark_frame(
    records: Sequence[MemoryPriceBenchmarkRecord],
    *,
    existing_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从基准价格 RAW 记录构建 Curated 表，并计算月环比 MoM 与同比 YoY 价格变动率。"""
    if not records:
        return empty_memory_benchmark()

    calendar = load_datatrack_release_calendar()
    records = sorted(records, key=lambda r: (r.product_family, r.indicator_id, r.trade_date))
    now_iso = datetime.now(UTC).isoformat()

    curated_release_dates: list[date | None] = []
    curated_release_statuses: list[str] = []
    for r in records:
        if r.release_date is not None:
            curated_release_dates.append(r.release_date)
            curated_release_statuses.append(r.release_date_status or "reported")
        elif r.report_month in calendar:
            curated_release_dates.append(calendar[r.report_month])
            curated_release_statuses.append("proxy_calendar")
        else:
            curated_release_dates.append(None)
            curated_release_statuses.append(r.release_date_status or "unavailable")

    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "product_family": [r.product_family for r in records],
        "indicator_id": [r.indicator_id for r in records],
        "indicator_name": [r.indicator_name for r in records],
        "price_usd": [r.price_usd for r in records],
        "price_mom": [None] * len(records),
        "price_yoy": [None] * len(records),
        "unit": [r.unit or "USD" for r in records],
        "source": [r.source or "TrendForce" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": curated_release_dates,
        "release_date_status": curated_release_statuses,
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=MEMORY_BENCHMARK_CURATED_SCHEMA)
        if existing_df is None or existing_df.is_empty()
        else pl.concat(
            [existing_df, pl.DataFrame(data, schema=MEMORY_BENCHMARK_CURATED_SCHEMA)],
            how="diagonal_relaxed",
        ).select(list(MEMORY_BENCHMARK_CURATED_SCHEMA))
    )

    if calendar and df["release_date"].is_null().any():
        cal_map_df = pl.DataFrame(
            {
                "report_month": list(calendar.keys()),
                "_proxy_rd": list(calendar.values()),
            },
            schema={"report_month": pl.String, "_proxy_rd": pl.Date},
        )
        df = (
            df.join(cal_map_df, on="report_month", how="left")
            .with_columns(
                pl.when(pl.col("release_date").is_null() & pl.col("_proxy_rd").is_not_null())
                .then(pl.col("_proxy_rd"))
                .otherwise(pl.col("release_date"))
                .alias("release_date"),
                pl.when(pl.col("release_date").is_null() & pl.col("_proxy_rd").is_not_null())
                .then(pl.lit("proxy_calendar"))
                .otherwise(pl.col("release_date_status"))
                .alias("release_date_status"),
            )
            .drop("_proxy_rd")
        )

    df = df.unique(subset=["report_month", "product_family", "indicator_id"], keep="last").sort(
        ["product_family", "indicator_id", "trade_date"]
    )

    frames = []
    for (_p_family, _ind_id), sub_df in df.group_by(
        ["product_family", "indicator_id"], maintain_order=True
    ):
        sub_df = sub_df.sort("trade_date")
        months = sub_df["report_month"].to_list()
        prices = sub_df["price_usd"].to_list()
        price_by_month = {
            m: float(p) for m, p in zip(months, prices, strict=False) if p is not None
        }
        mom: list[float | None] = [_growth_for_month(m, price_by_month, 1) for m in months]
        yoy: list[float | None] = [_growth_for_month(m, price_by_month, 12) for m in months]

        frames.append(
            sub_df.with_columns(
                pl.Series("price_mom", mom, dtype=pl.Float64),
                pl.Series("price_yoy", yoy, dtype=pl.Float64),
            )
        )

    return pl.concat(frames) if frames else empty_memory_benchmark()


def _growth_for_month(
    report_month: str,
    prices_by_month: dict[str, float],
    months_back: int,
) -> float | None:
    year, month = parse_month_string(report_month)
    index = year * 12 + month - 1 - months_back
    previous_month = index % 12 + 1
    previous_year = index // 12
    previous = prices_by_month.get(f"{previous_year:04d}-{previous_month:02d}")
    current = prices_by_month.get(report_month)
    if current is None or previous is None or previous <= 0:
        return None
    return round(current / previous - 1.0, 4)
