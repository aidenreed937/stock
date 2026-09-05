"""全球半导体月度销售额 (SIA/WSTS) Schema 定义与转换器。"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import (
    SemiconductorLeadRecord,
    SemiconductorSalesRecord,
)
from stock_data.fetcher.industry.semiconductor.schemas import (
    SEMICONDUCTOR_LEAD_RAW_SCHEMA,
    SEMICONDUCTOR_LEAD_SCHEMA,
    SEMICONDUCTOR_SALES_RAW_SCHEMA,
    SEMICONDUCTOR_SALES_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.lead import (
    convert_ntd_to_usd,
    derive_tsmc_mom,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def _source_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def empty_raw_semiconductor_sales() -> pl.DataFrame:
    """构造半导体销售额 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_SALES_RAW_SCHEMA)


def records_to_raw_semiconductor_frame(
    records: Sequence[SemiconductorSalesRecord],
) -> pl.DataFrame:
    """将半导体销售额记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_semiconductor_sales()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "worldwide_raw": [r.worldwide_raw for r in records],
        "americas_raw": [r.americas_raw for r in records],
        "europe_raw": [r.europe_raw for r in records],
        "japan_raw": [r.japan_raw for r in records],
        "asia_pacific_raw": [r.asia_pacific_raw for r in records],
        "china_sales_raw": [r.china_sales_raw for r in records],
        "china_yoy_growth_raw": [r.china_yoy_growth_raw for r in records],
        "china_mom_growth_raw": [r.china_mom_growth_raw for r in records],
        "source": [r.source or "SIA/WSTS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=SEMICONDUCTOR_SALES_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def records_to_raw_semiconductor_sales_frame(
    records: Sequence[SemiconductorSalesRecord],
) -> pl.DataFrame:
    """将半导体销售额记录转换为纯源端 RAW 表（显式销售额命名别名）。"""
    return records_to_raw_semiconductor_frame(records)


def empty_semiconductor_sales() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_SALES_SCHEMA)


def records_to_semiconductor_frame(
    records: Sequence[SemiconductorSalesRecord],
) -> pl.DataFrame:
    """从销售额 RAW 字段构建 Curated 表，并计算全球销售额 YoY/MoM。"""
    if not records:
        return empty_semiconductor_sales()

    records = list(records)
    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "global_sales_usd": [
            _wsts_billion_usd(r.worldwide_raw, r.global_sales_usd) for r in records
        ],
        "china_sales_usd": [
            _source_billion_usd(r.china_sales_raw, r.china_sales_usd) for r in records
        ],
        "china_yoy_growth": [
            _source_percent(r.china_yoy_growth_raw, r.china_yoy_growth) for r in records
        ],
        "china_mom_growth": [
            _source_percent(r.china_mom_growth_raw, r.china_mom_growth) for r in records
        ],
        "americas_sales_usd": [
            _wsts_billion_usd(r.americas_raw, r.americas_sales_usd) for r in records
        ],
        "europe_sales_usd": [_wsts_billion_usd(r.europe_raw, r.europe_sales_usd) for r in records],
        "japan_sales_usd": [_wsts_billion_usd(r.japan_raw, r.japan_sales_usd) for r in records],
        "asia_pacific_sales_usd": [
            _wsts_billion_usd(r.asia_pacific_raw, r.asia_pacific_sales_usd) for r in records
        ],
        "yoy_growth": [None] * len(records),
        "mom_growth": [None] * len(records),
        "unit": ["billion_usd"] * len(records),
        "source": [r.source or "SIA/WSTS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=SEMICONDUCTOR_SALES_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    sales_by_month = {
        str(row["report_month"]): row["global_sales_usd"]
        for row in df.select(["report_month", "global_sales_usd"]).to_dicts()
        if row["global_sales_usd"] is not None
    }
    yoy = [_growth_for_month(month, sales_by_month, 12) for month in df["report_month"]]
    mom = [_growth_for_month(month, sales_by_month, 1) for month in df["report_month"]]
    return df.with_columns(
        pl.Series("yoy_growth", yoy, dtype=pl.Float64),
        pl.Series("mom_growth", mom, dtype=pl.Float64),
    )


def _wsts_billion_usd(raw_value: str | None, fallback: float | None) -> float | None:
    """将 WSTS 3MMA 原始单元 (千美元) 转成 Curated 十亿美元。"""
    parsed = _parse_number(raw_value)
    if parsed is not None:
        return round(parsed / 1_000_000.0, 3)
    return round(float(fallback), 3) if fallback is not None else None


def _source_billion_usd(raw_value: str | None, fallback: float | None) -> float | None:
    """将 SIA 中国区原始单元 (十亿美元) 转成 Curated 数值。"""
    parsed = _parse_number(raw_value)
    if parsed is not None:
        return round(parsed, 3)
    return round(float(fallback), 3) if fallback is not None else None


def _source_percent(raw_value: str | None, fallback: float | None) -> float | None:
    """将 SIA 原始百分比转成小数；无 raw 时保留兼容模型中的小数值。"""
    parsed = _parse_number(raw_value)
    if parsed is not None:
        raw_text = str(raw_value).lower() if raw_value else ""
        value = parsed / 100.0 if "%" in raw_text or "percent" in raw_text else parsed
        # SIA 的原文可能用 decreased 表达负号，raw 字段只保存括号中的原始数字。
        if fallback is not None and fallback < 0 < value:
            return round(float(fallback), 4)
        return round(value, 4)
    return round(float(fallback), 4) if fallback is not None else None


def _parse_number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value).replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


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


def empty_raw_semiconductor_lead() -> pl.DataFrame:
    """构造半导体先导指标 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_LEAD_RAW_SCHEMA)


def records_to_raw_semiconductor_lead_frame(
    records: Sequence[SemiconductorLeadRecord],
) -> pl.DataFrame:
    """将台积电月营收记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_semiconductor_lead()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "month_raw": [r.tsmc_month_raw for r in records],
        "net_revenue_raw": [r.tsmc_revenue_raw for r in records],
        "yoy_change_raw": [r.tsmc_revenue_yoy_raw for r in records],
        "source": [r.source or "TSMC" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=SEMICONDUCTOR_LEAD_RAW_SCHEMA)
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        ),
        "semiconductor_lead",
    )


def empty_semiconductor_lead() -> pl.DataFrame:
    """构造半导体先导指标空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_LEAD_SCHEMA)


def records_to_semiconductor_lead_frame(
    records: Sequence[SemiconductorLeadRecord],
    *,
    runtime: DataRuntimeContext | None = None,
) -> pl.DataFrame:
    """将半导体先导指标记录转换为强类型 Polars DataFrame，并计算 3MMA。"""
    if not records:
        return empty_semiconductor_lead()

    now_iso = datetime.now(UTC).isoformat()
    mom_by_month = derive_tsmc_mom(records)
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "tsmc_revenue_ntd_million": [r.tsmc_revenue_ntd_million for r in records],
        "tsmc_revenue_usd_million": [
            r.tsmc_revenue_usd_million
            if r.tsmc_revenue_usd_million is not None
            else convert_ntd_to_usd(
                r.tsmc_revenue_ntd_million,
                r.report_month,
                runtime=runtime,
            )
            for r in records
        ],
        "tsmc_revenue_yoy": [r.tsmc_revenue_yoy for r in records],
        "tsmc_revenue_mom": [mom_by_month.get(r.report_month) for r in records],
        "tsmc_revenue_3mma_usd": [r.tsmc_revenue_3mma_usd for r in records],
        "unit": [r.unit or "million_ntd/usd" for r in records],
        "source": [r.source or "TSMC" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=SEMICONDUCTOR_LEAD_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    if (
        df["tsmc_revenue_3mma_usd"].is_null().all()
        and df["tsmc_revenue_usd_million"].is_not_null().any()
    ):
        df = df.with_columns(
            pl.col("tsmc_revenue_usd_million")
            .rolling_mean(window_size=3, min_samples=1)
            .round(2)
            .alias("tsmc_revenue_3mma_usd")
        )

    return df
