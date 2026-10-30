"""智库 CoWoS 产能测算与供需推演 Curated 转换器 (CowosEstimatesTransform).

负责计算产能同比、环比（小数制）以及推演供需瓶颈相态 (bottleneck_regime)，
并保证预测数据与官方实际数据在物理层面完全解耦。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.semiconductor.models import CowosCapacityEstimateRecord
from stock_data.fetcher.industry.semiconductor.schemas import (
    COWOS_CAPACITY_ESTIMATES_CURATED_SCHEMA,
    COWOS_CAPACITY_ESTIMATES_RAW_SCHEMA,
)


def build_cowos_capacity_estimates_raw_frame(
    records: Sequence[CowosCapacityEstimateRecord],
) -> pl.DataFrame:
    """将智库测算原始记录转为 RAW DataFrame。"""
    if not records:
        return pl.DataFrame(schema=COWOS_CAPACITY_ESTIMATES_RAW_SCHEMA)

    data = [
        {
            "symbol": r.symbol,
            "report_quarter": r.report_quarter,
            "trade_date": r.trade_date,
            "agency": r.agency,
            "published_date": r.published_date,
            "monthly_capacity_kwpm": r.monthly_capacity_kwpm,
            "lead_time_months": r.lead_time_months,
            "data_status": r.data_status,
            "source": r.source,
            "source_url": r.source_url,
            "collected_at": r.collected_at,
            "raw_content_sha256": r.raw_content_sha256,
            "raw_snapshot_path": r.raw_snapshot_path,
        }
        for r in records
    ]
    df = pl.DataFrame(data)
    return df.cast(COWOS_CAPACITY_ESTIMATES_RAW_SCHEMA)


def build_cowos_capacity_estimates_curated_frame(
    records: Sequence[CowosCapacityEstimateRecord],
) -> pl.DataFrame:
    """构建智库 CoWoS 产能测算与前瞻供需相态 Curated 事实表。"""
    if not records:
        return pl.DataFrame(schema=COWOS_CAPACITY_ESTIMATES_CURATED_SCHEMA)

    # 按机构、报告期、发布日升序排序；同一报告期的多条记录是预测修订，必须保留。
    sorted_records = sorted(records, key=lambda r: (r.agency, r.trade_date, r.published_date))
    raw_df = build_cowos_capacity_estimates_raw_frame(sorted_records)

    # 计算 YoY/QoQ 时使用“截至该行 published_date 可见”的版本，避免同一报告期
    # 的预测修订值互相产生伪环比，也避免把未来修订带入历史预测。
    curated_records = []
    rows_by_agency: dict[str, list[dict[str, object]]] = {}
    for row in raw_df.to_dicts():
        rows_by_agency.setdefault(str(row["agency"]), []).append(row)

    for agency_rows in rows_by_agency.values():
        agency_rows.sort(
            key=lambda row: (_quarter_key(str(row["report_quarter"])), row["published_date"])
        )
        for row in agency_rows:
            cap = float(str(row["monthly_capacity_kwpm"]))
            lead = row["lead_time_months"]
            current_quarter = _quarter_key(str(row["report_quarter"]))
            published_date = str(row["published_date"])
            visible_rows = [
                candidate
                for candidate in agency_rows
                if str(candidate["published_date"]) <= published_date
            ]

            previous_period = _latest_visible_period(
                visible_rows,
                current_quarter=current_quarter,
                target_quarter=None,
            )
            qoq = _growth(cap, previous_period)

            yoy_period = _latest_visible_period(
                visible_rows,
                current_quarter=current_quarter,
                target_quarter=current_quarter - 4,
            )
            yoy = _growth(cap, yoy_period)

            # 判定 bottleneck_regime
            if yoy is not None and yoy >= 0.80 and lead is not None and float(str(lead)) >= 6.0:
                regime = "severe_bottleneck_expansion"
            elif (yoy is not None and yoy >= 0.30) or (qoq is not None and qoq >= 0.25):
                regime = "moderate_expansion"
            else:
                regime = "balanced_or_mature"

            curated_records.append(
                {
                    "symbol": row["symbol"],
                    "report_quarter": row["report_quarter"],
                    "trade_date": row["trade_date"],
                    "agency": row["agency"],
                    "published_date": row["published_date"],
                    "monthly_capacity_kwpm": cap,
                    "lead_time_months": lead,
                    "capacity_yoy": yoy,
                    "capacity_qoq": qoq,
                    "bottleneck_regime": regime,
                    "unit": "kwpm",
                    "source": row["source"],
                    "source_url": row["source_url"],
                    "data_status": row["data_status"],
                    "collected_at": row["collected_at"],
                }
            )

    curated_df = pl.DataFrame(curated_records)
    return curated_df.cast(COWOS_CAPACITY_ESTIMATES_CURATED_SCHEMA)


def _quarter_key(value: str) -> int:
    match = re.fullmatch(r"(\d{4})-?Q([1-4])", value)
    if match is None:
        raise ValueError(f"无法解析 CoWoS 报告季度: {value!r}")
    return int(match.group(1)) * 4 + int(match.group(2))


def _latest_visible_period(
    rows: list[dict[str, object]],
    *,
    current_quarter: int,
    target_quarter: int | None,
) -> float | None:
    candidates = [
        row
        for row in rows
        if (
            _quarter_key(str(row["report_quarter"])) == target_quarter
            if target_quarter is not None
            else _quarter_key(str(row["report_quarter"])) < current_quarter
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (str(row["published_date"]), str(row.get("trade_date", ""))))
    value = candidates[-1]["monthly_capacity_kwpm"]
    return float(str(value)) if value is not None else None


def _growth(current: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous, 4)
