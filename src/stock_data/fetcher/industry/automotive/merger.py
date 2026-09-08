"""汽车多源月度记录合并与窗口判断。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string


def merge_record(
    existing: NevMonthlyRecord | None,
    incoming: NevMonthlyRecord,
) -> NevMonthlyRecord:
    """按月份合并不同来源的字段，空值不覆盖已有事实。"""
    return _merge_info(
        existing,
        {
            "report_month": incoming.report_month,
            "trade_date": incoming.trade_date,
            "wholesale_volume_ten_thousand": incoming.wholesale_volume_ten_thousand,
            "total_volume_ten_thousand": incoming.total_volume_ten_thousand,
            "retail_volume_ten_thousand": incoming.retail_volume_ten_thousand,
            "export_volume_ten_thousand": incoming.export_volume_ten_thousand,
            "penetration_rate": incoming.penetration_rate,
            "battery_installation_gwh": incoming.battery_installation_gwh,
            "yoy_growth": incoming.yoy_growth,
            "unit": incoming.unit,
            "source": incoming.source,
            "source_url": incoming.source_url,
            "release_date": incoming.release_date,
            "data_status": incoming.data_status,
            "collected_at": incoming.collected_at,
            "wholesale_volume_raw": incoming.wholesale_volume_raw,
            "total_volume_raw": incoming.total_volume_raw,
            "retail_volume_raw": incoming.retail_volume_raw,
            "export_volume_raw": incoming.export_volume_raw,
            "penetration_rate_raw": incoming.penetration_rate_raw,
            "battery_installation_gwh_raw": incoming.battery_installation_gwh_raw,
            "yoy_growth_raw": incoming.yoy_growth_raw,
            "raw_content_sha256": incoming.raw_content_sha256,
            "raw_snapshot_path": incoming.raw_snapshot_path,
        },
    )


def month_keys(start_date: date | None, end_date: date | None) -> list[str]:
    if start_date is None and end_date is None:
        return []
    cursor = (start_date or end_date).replace(day=1)  # type: ignore[union-attr]
    end = (end_date or start_date).replace(day=1)  # type: ignore[union-attr]
    result: list[str] = []
    while cursor <= end:
        result.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def record_in_range(
    record: NevMonthlyRecord,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    if start_date is not None and record.trade_date < start_date:
        return False
    if end_date is not None and record.trade_date > end_date:
        return False
    return True


def _merge_info(
    existing: NevMonthlyRecord | None,
    info: dict[str, object],
) -> NevMonthlyRecord:
    report_month = str(info["report_month"])
    year, month = parse_month_string(report_month)
    incoming_unit = str(info.get("unit") or "ten_thousand_units")
    if existing is None:
        existing = NevMonthlyRecord(
            report_month=report_month,
            trade_date=get_month_end_date(year, month),
            unit=incoming_unit,
            source=str(info.get("source") or "CPCA"),
            source_url=str(info.get("source_url") or ""),
        )

    merged_source = merge_sources(existing.source, info.get("source"))
    values: dict[str, Any] = {
        "trade_date": get_month_end_date(year, month),
        "source": merged_source,
        "source_url": merge_text(existing.source_url, info.get("source_url")),
        "release_date": _coerce_date(info.get("release_date")) or existing.release_date,
        "data_status": str(info.get("data_status") or existing.data_status or "actual"),
        "collected_at": str(info.get("collected_at") or existing.collected_at or now_utc_iso()),
        "unit": "mixed" if "/" in merged_source else existing.unit or incoming_unit,
        "raw_content_sha256": merge_text(
            existing.raw_content_sha256, info.get("raw_content_sha256")
        ),
        "raw_snapshot_path": merge_text(existing.raw_snapshot_path, info.get("raw_snapshot_path")),
    }
    for numeric_name, raw_name in (
        ("wholesale_volume_ten_thousand", "wholesale_volume_raw"),
        ("total_volume_ten_thousand", "total_volume_raw"),
        ("retail_volume_ten_thousand", "retail_volume_raw"),
        ("export_volume_ten_thousand", "export_volume_raw"),
        ("penetration_rate", "penetration_rate_raw"),
        ("battery_installation_gwh", "battery_installation_gwh_raw"),
        ("yoy_growth", "yoy_growth_raw"),
    ):
        incoming_value = info.get(numeric_name)
        if incoming_value is not None:
            values[numeric_name] = incoming_value
        incoming_raw = info.get(raw_name)
        if incoming_raw is None and incoming_value is not None:
            incoming_raw = str(incoming_value)
        if incoming_raw is not None:
            values[raw_name] = str(incoming_raw)
    return replace(existing, **values)


def merge_sources(existing: str, incoming: object) -> str:
    values = [value for value in (existing, str(incoming or "")) if value]
    parts: list[str] = []
    for value in values:
        for part in value.split("/"):
            if part and part not in parts:
                parts.append(part)
    return "/".join(parts) or "CPCA"


def merge_text(existing: str, incoming: object) -> str:
    values = [value for value in (existing, str(incoming or "")) if value]
    parts: list[str] = []
    for value in values:
        for part in value.split(";"):
            if part and part not in parts:
                parts.append(part)
    return ";".join(parts)


def _coerce_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


__all__ = [
    "merge_record",
    "merge_sources",
    "merge_text",
    "month_keys",
    "record_in_range",
]
