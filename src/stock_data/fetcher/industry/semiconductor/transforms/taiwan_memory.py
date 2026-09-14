"""台湾存储龙头 (南亚科/威刚) 月度营运营收 Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import TaiwanMemoryLeadRecord
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)
from stock_data.pipeline.normalizer.unit_normalizer import UnitNormalizer

TAIWAN_MEMORY_LEAD_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "symbol": pl.String,
    "company_name_raw": pl.String,
    "report_month_raw": pl.String,
    "net_revenue_raw": pl.String,
    "last_year_revenue_raw": pl.String,
    "yoy_change_raw": pl.String,
    "mom_change_raw": pl.String,
    "cumulative_revenue_raw": pl.String,
    "cumulative_yoy_raw": pl.String,
    "unit_raw": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "release_date_raw": pl.String,
    "release_date_status": pl.String,
    "source_response_datetime_raw": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

TAIWAN_MEMORY_LEAD_CURATED_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "symbol": pl.String,
    "company_name": pl.String,
    "revenue_ntd_million": pl.Float64,
    "revenue_usd_million": pl.Float64,
    "revenue_yoy": pl.Float64,
    "revenue_yoy_derived": pl.Float64,
    "revenue_mom": pl.Float64,
    "revenue_3mma_usd": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "release_date_status": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_raw_taiwan_memory_lead() -> pl.DataFrame:
    """构造台湾存储龙头月营收 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=TAIWAN_MEMORY_LEAD_RAW_SCHEMA)


def records_to_raw_taiwan_memory_lead_frame(
    records: Sequence[TaiwanMemoryLeadRecord],
) -> pl.DataFrame:
    """将台湾存储月度出货记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_taiwan_memory_lead()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "symbol": [r.symbol for r in records],
        "company_name_raw": [r.company_name_raw for r in records],
        "report_month_raw": [r.report_month_raw for r in records],
        "net_revenue_raw": [r.net_revenue_raw for r in records],
        "last_year_revenue_raw": [r.last_year_revenue_raw for r in records],
        "yoy_change_raw": [r.yoy_change_raw for r in records],
        "mom_change_raw": [r.mom_change_raw for r in records],
        "cumulative_revenue_raw": [r.cumulative_revenue_raw for r in records],
        "cumulative_yoy_raw": [r.cumulative_yoy_raw for r in records],
        "unit_raw": [r.unit or "thousand_ntd" for r in records],
        "source": [r.source or "MOPS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "release_date_raw": [r.release_date_raw for r in records],
        "release_date_status": [r.release_date_status for r in records],
        "source_response_datetime_raw": [r.source_response_datetime_raw for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=TAIWAN_MEMORY_LEAD_RAW_SCHEMA)
            .unique(subset=["report_month", "symbol"], keep="last")
            .sort(["symbol", "trade_date"])
        ),
        "semiconductor_memory_taiwan_lead",
        allow_unavailable=True,
    )


def empty_taiwan_memory_lead() -> pl.DataFrame:
    """构造台湾存储龙头月营收 Curated 空事实表骨架。"""
    return pl.DataFrame(schema=TAIWAN_MEMORY_LEAD_CURATED_SCHEMA)


def records_to_taiwan_memory_lead_frame(
    records: Sequence[TaiwanMemoryLeadRecord],
    *,
    runtime: DataRuntimeContext | None = None,
    existing_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从台湾存储出货 RAW 记录构建 Curated 表，折算 USD 营收并计算 3MMA。"""
    if not records:
        return empty_taiwan_memory_lead()

    records = sorted(records, key=lambda r: (r.symbol, r.trade_date))
    now_iso = datetime.now(UTC).isoformat()

    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "symbol": [r.symbol for r in records],
        "company_name": [r.company_name for r in records],
        "revenue_ntd_thousand": [r.revenue_ntd_thousand for r in records],
        "revenue_yoy": [r.revenue_yoy for r in records],
        "revenue_yoy_derived": [None] * len(records),
        "revenue_mom": [r.revenue_mom for r in records],
        "revenue_3mma_usd": [None] * len(records),
        "unit": ["million_ntd/usd"] * len(records),
        "source": [r.source or "MOPS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "release_date_status": [r.release_date_status for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        UnitNormalizer("industry", "semiconductor_memory_taiwan_lead", runtime=runtime)
        .normalize_units(pl.DataFrame(data))
        .select(list(TAIWAN_MEMORY_LEAD_CURATED_SCHEMA))
    )
    if existing_df is not None and not existing_df.is_empty():
        df = pl.concat([existing_df, df], how="diagonal_relaxed").select(
            list(TAIWAN_MEMORY_LEAD_CURATED_SCHEMA)
        )
    df = df.unique(subset=["report_month", "symbol"], keep="last").sort(["symbol", "trade_date"])

    frames = []
    for _symbol_val, sub_df in df.group_by(["symbol"], maintain_order=True):
        sub_df = sub_df.sort("trade_date")
        months = sub_df["report_month"].to_list()
        ntd = sub_df["revenue_ntd_million"].to_list()
        usd = sub_df["revenue_usd_million"].to_list()
        yoy_derived: list[float | None] = [None] * len(sub_df)
        mom = sub_df["revenue_mom"].to_list()
        mma3: list[float | None] = [None] * len(sub_df)

        ntd_by_month = {m: float(v) for m, v in zip(months, ntd, strict=False) if v is not None}
        for i in range(len(sub_df)):
            yoy_derived[i] = _growth_for_month(months[i], ntd_by_month, 12)
            # 补齐未自带的 MoM
            if mom[i] is None:
                mom[i] = _growth_for_month(months[i], ntd_by_month, 1)
            # 计算 USD 3MMA
            if i >= 2 and _month_lag(months[i - 2], months[i]) == 2:
                v0, v1, v2 = usd[i - 2], usd[i - 1], usd[i]
                if v0 is not None and v1 is not None and v2 is not None:
                    mma3[i] = round((v0 + v1 + v2) / 3.0, 2)

        frames.append(
            sub_df.with_columns(
                pl.Series("revenue_yoy_derived", yoy_derived, dtype=pl.Float64),
                pl.Series("revenue_mom", mom, dtype=pl.Float64),
                pl.Series("revenue_3mma_usd", mma3, dtype=pl.Float64),
            )
        )

    return pl.concat(frames) if frames else empty_taiwan_memory_lead()


def _growth_for_month(
    report_month: str,
    sales_by_month: dict[str, float],
    months_back: int,
) -> float | None:
    year, month = parse_month_string(report_month)
    index = year * 12 + month - 1 - months_back
    previous_month = index % 12 + 1
    previous_year = index // 12
    previous = sales_by_month.get(f"{previous_year:04d}-{previous_month:02d}")
    current = sales_by_month.get(report_month)
    if current is None or previous is None or previous <= 0:
        return None
    return round(current / previous - 1.0, 4)


def _month_lag(left: str, right: str) -> int:
    left_year, left_month = parse_month_string(left)
    right_year, right_month = parse_month_string(right)
    return (right_year * 12 + right_month) - (left_year * 12 + left_month)
