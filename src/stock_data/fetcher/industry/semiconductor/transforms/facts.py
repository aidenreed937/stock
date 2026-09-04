"""全球半导体月度销售额 (SIA/WSTS) Schema 定义与转换器。"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import (
    ChipLeadTimeRecord,
    SemiconductorEquipmentRecord,
    SemiconductorLeadRecord,
    SemiconductorSalesRecord,
)
from stock_data.fetcher.industry.semiconductor.schemas import (
    CHIP_LEAD_TIME_RAW_SCHEMA,
    CHIP_LEAD_TIME_SCHEMA,
    SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA,
    SEMICONDUCTOR_EQUIPMENT_SCHEMA,
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
            else convert_ntd_to_usd(r.tsmc_revenue_ntd_million, r.report_month)
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


def empty_raw_chip_lead_time() -> pl.DataFrame:
    """构造芯片交期先导指标 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=CHIP_LEAD_TIME_RAW_SCHEMA)


def records_to_raw_chip_lead_time_frame(
    records: Sequence[ChipLeadTimeRecord],
) -> pl.DataFrame:
    """将芯片交期记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_chip_lead_time()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "lead_time_raw": [r.lead_time_raw for r in records],
        "sku_details_raw": [r.sku_details_raw for r in records],
        "source": [r.source or "Susquehanna/Distributor" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=CHIP_LEAD_TIME_RAW_SCHEMA)
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        ),
        "chip_lead_time",
    )


def empty_chip_lead_time() -> pl.DataFrame:
    """构造芯片交期先导指标空事实表骨架。"""
    return pl.DataFrame(schema=CHIP_LEAD_TIME_SCHEMA)


def records_to_chip_lead_time_frame(
    records: Sequence[ChipLeadTimeRecord],
) -> pl.DataFrame:
    """将芯片交期记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_chip_lead_time()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "avg_lead_time_weeks": [r.avg_lead_time_weeks for r in records],
        "mcu_lead_time_weeks": [r.mcu_lead_time_weeks for r in records],
        "analog_lead_time_weeks": [r.analog_lead_time_weeks for r in records],
        "discrete_lead_time_weeks": [r.discrete_lead_time_weeks for r in records],
        "compute_lead_time_weeks": [r.compute_lead_time_weeks for r in records],
        "lead_time_yoy_weeks": [r.lead_time_yoy_weeks for r in records],
        "lead_time_mom_weeks": [r.lead_time_mom_weeks for r in records],
        "lead_time_status": [r.lead_time_status for r in records],
        "unit": [r.unit or "weeks" for r in records],
        "source": [r.source or "Susquehanna/Distributor" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=CHIP_LEAD_TIME_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    if len(df) > 1:
        df = df.with_columns(
            (pl.col("avg_lead_time_weeks") - pl.col("avg_lead_time_weeks").shift(1))
            .round(2)
            .alias("lead_time_mom_weeks"),
            (pl.col("avg_lead_time_weeks") - pl.col("avg_lead_time_weeks").shift(12))
            .round(2)
            .alias("lead_time_yoy_weeks"),
        )
    return df


def empty_raw_semiconductor_equipment() -> pl.DataFrame:
    """构造半导体设备出货 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA)


def records_to_raw_semiconductor_equipment_frame(
    records: Sequence[SemiconductorEquipmentRecord],
) -> pl.DataFrame:
    """将半导体设备出货记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_semiconductor_equipment()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "sales_3mma_raw": [r.billings_raw or _source_string(r.billings_jpy_raw) for r in records],
        "mom_growth_3mma_raw": [r.mom_raw or _source_string(r.mom_reported) for r in records],
        "yoy_growth_3mma_raw": [r.yoy_raw or _source_string(r.yoy_reported) for r in records],
        "source": [r.source or "SEAJ" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA)
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        ),
        "semiconductor_equipment",
    )


def empty_semiconductor_equipment() -> pl.DataFrame:
    """构造半导体设备出货空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)


def records_to_semiconductor_equipment_frame(
    records: Sequence[SemiconductorEquipmentRecord],
) -> pl.DataFrame:
    """将半导体设备出货记录转换为 Curated 表并补算缺失的 3MMA 增速。"""
    if not records:
        return empty_semiconductor_equipment()

    ordered_records = sorted(records, key=lambda record: record.report_month)
    now_iso = datetime.now(UTC).isoformat()
    billings_3mma = [
        _equipment_3mma_billion(
            r.billings_raw or _source_string(r.billings_jpy_raw),
            r.billings_3mma_jpy,
        )
        for r in ordered_records
    ]
    yoy_3mma = [
        _equipment_percent(r.yoy_raw or _source_string(r.yoy_reported), r.yoy_growth_3mma)
        for r in ordered_records
    ]
    mom_3mma = [
        _equipment_percent(r.mom_raw or _source_string(r.mom_reported), r.mom_growth_3mma)
        for r in ordered_records
    ]
    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "billings_3mma_jpy": billings_3mma,
        "yoy_growth_3mma": yoy_3mma,
        "mom_growth_3mma": mom_3mma,
        "unit": [r.unit or "billion_jpy" for r in ordered_records],
        "source": [r.source or "SEAJ" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }

    df = (
        pl.DataFrame(data, schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    return _fill_semiconductor_equipment_growth(df)


def _fill_semiconductor_equipment_growth(df: pl.DataFrame) -> pl.DataFrame:
    """按连续报告月从 SEAJ 3MMA 源值补算缺失的 MoM/YoY。"""
    months = df["report_month"].to_list()
    values = df["billings_3mma_jpy"].to_list()
    mom = df["mom_growth_3mma"].to_list()
    yoy = df["yoy_growth_3mma"].to_list()

    for index, value in enumerate(values):
        if value is None or float(value) <= 0:
            continue
        if (
            mom[index] is None
            and index >= 1
            and _month_lag(months[index - 1], months[index]) == 1
            and values[index - 1] is not None
            and float(values[index - 1]) > 0
        ):
            mom[index] = round(float(value) / float(values[index - 1]) - 1.0, 4)
        if (
            yoy[index] is None
            and index >= 12
            and _month_lag(months[index - 12], months[index]) == 12
            and values[index - 12] is not None
            and float(values[index - 12]) > 0
        ):
            yoy[index] = round(float(value) / float(values[index - 12]) - 1.0, 4)

    return df.with_columns(
        pl.Series("mom_growth_3mma", mom, dtype=pl.Float64),
        pl.Series("yoy_growth_3mma", yoy, dtype=pl.Float64),
    )


def _equipment_3mma_billion(raw_value: Any, fallback: float | None) -> float | None:
    parsed = _parse_number(raw_value)
    if parsed is not None:
        return round(parsed / 1000.0, 2)
    return round(float(fallback), 2) if fallback is not None else None


def _equipment_percent(raw_value: Any, fallback: float | None) -> float | None:
    parsed = _parse_number(raw_value)
    if parsed is not None:
        value = parsed / 100.0 if raw_value is not None and "%" in str(raw_value) else parsed
        return round(value, 4)
    return round(float(fallback), 4) if fallback is not None else None


def _month_lag(left: str, right: str) -> int:
    left_year, left_month = parse_month_string(left)
    right_year, right_month = parse_month_string(right)
    return (right_year * 12 + right_month) - (left_year * 12 + left_month)
