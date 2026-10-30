"""化工月度事实的采集前质量校验。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

import polars as pl

from stock_data.fetcher.industry.chemicals.models import (
    ChemicalMarketRecord,
    ChemicalSpotPriceRecord,
)
from stock_data.fetcher.industry.common import get_month_end_date, parse_month_string

_NON_NEGATIVE_FIELDS = (
    "soda_ash_production",
    "caustic_soda_production",
    "synthetic_fiber_production",
    "chemical_fertilizer_production",
    "plastics_production",
    "plate_glass_production",
    "spot_soda_ash_price_cny",
    "spot_pta_price_cny",
    "spot_urea_price_cny",
    "spot_mdi_price_cny",
    "spot_tio2_price_cny",
    "spot_refrigerant_r32_price_cny",
    "chemical_social_inventory",
)
_RATE_FIELDS = ("soda_ash_operating_rate", "pta_operating_rate")
_ALLOWED_STATUSES = frozenset(
    {
        "actual",
        "cached",
        "mixed",
        "source_reported",
        "verified_industry_report",
    }
)


def validate_chemical_market_records(
    records: Iterable[ChemicalMarketRecord],
    *,
    as_of_date: date | None = None,
) -> tuple[list[ChemicalMarketRecord], tuple[str, ...]]:
    """拒绝结构、数值和发布时间明显不可信的月度事实。

    缺失值保持缺失，不做插值或前值填充。``as_of_date`` 只有在调用方明确提供时，
    才用于检查发布日期，避免把报告期末错误当成信息可得日。
    """
    valid: list[ChemicalMarketRecord] = []
    errors: list[str] = []
    seen_months: set[str] = set()

    for record in records:
        prefix = record.report_month or "<empty>"
        record_errors: list[str] = []
        try:
            year, month = parse_month_string(record.report_month)
            expected_trade_date = get_month_end_date(year, month)
            if record.trade_date != expected_trade_date:
                record_errors.append(
                    f"trade_date={record.trade_date} 与 report_month={record.report_month} 不一致"
                )
        except (TypeError, ValueError):
            record_errors.append("report_month 不是有效的 YYYY-MM")

        if record.report_month in seen_months:
            record_errors.append("report_month 重复")
        seen_months.add(record.report_month)

        if record.release_date is not None and as_of_date is not None:
            if record.release_date > as_of_date:
                record_errors.append(
                    f"release_date={record.release_date} 晚于 as_of_date={as_of_date}"
                )

        if record.data_status not in _ALLOWED_STATUSES:
            record_errors.append(f"未知 data_status={record.data_status!r}")

        for field in _NON_NEGATIVE_FIELDS:
            value = getattr(record, field)
            if value is not None and (not math.isfinite(value) or value < 0):
                record_errors.append(f"{field}={value!r} 不是合法非负数")
        for field in _RATE_FIELDS:
            value = getattr(record, field)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
                record_errors.append(f"{field}={value!r} 不在 0~100% 范围")

        for field, source_field in (
            ("spot_mdi_price_cny", "mdi_source"),
            ("spot_tio2_price_cny", "tio2_source"),
        ):
            if (
                getattr(record, field) is not None
                and not str(getattr(record, source_field) or "").strip()
            ):
                record_errors.append(f"{field} 缺少字段级来源 {source_field}")

        if record_errors:
            errors.extend(f"{prefix}: {message}" for message in record_errors)
        else:
            valid.append(record)

    return valid, tuple(errors)


def validate_capacity_raw_frame(
    frame: pl.DataFrame,
    *,
    as_of_date: date | None = None,
) -> tuple[str, ...]:
    """校验化工事实底座 RAW 的结构和已提供数值，不拒绝合法缺失值。"""
    errors: list[str] = []
    for index, row in enumerate(frame.to_dicts()):
        prod = str(row.get("product_name") or "")
        month = str(row.get("report_month") or f"row-{index}")
        label = f"{prod}:{month}" if prod else month
        report_month = str(row.get("report_month") or "")
        try:
            year, m_val = parse_month_string(report_month)
            trade_date = row.get("trade_date")
            if trade_date is not None and trade_date != date(year, m_val, 1):
                errors.append(f"{label}: trade_date 与 report_month 不一致")
        except (TypeError, ValueError):
            errors.append(f"{label}: report_month 不是有效的 YYYY-MM")

        for field in ("output_current_raw", "annual_capacity_raw"):
            value = _safe_float(row.get(field))
            raw_value = str(row.get(field) or "").strip()
            if raw_value and value is None:
                errors.append(f"{label}: {field} 不是有限数值")
            elif value is not None and (not math.isfinite(value) or value < 0):
                errors.append(f"{label}: {field} 不是合法非负数")

        release_date = row.get("release_date")
        if release_date is not None and as_of_date is not None and release_date > as_of_date:
            errors.append(f"{label}: release_date 晚于 as_of_date")
    return tuple(errors)


def validate_spread_raw_rows(
    frame: pl.DataFrame,
    *,
    as_of_date: date | None = None,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """校验价差 RAW，并返回允许进入 Curated 的行号。"""
    valid_indices: list[int] = []
    errors: list[str] = []
    required_text = ("product_name", "symbol", "process_type", "source")
    required_numeric = (
        "product_price_cny_raw",
        "raw_material_cost_cny_raw",
        "spread_margin_cny_raw",
    )
    for index, row in enumerate(frame.to_dicts()):
        label = f"row-{index}"
        row_errors: list[str] = []
        if row.get("trade_date") is None:
            row_errors.append("trade_date 缺失")
        for field in required_text:
            if not str(row.get(field) or "").strip():
                row_errors.append(f"{field} 缺失")
        for field in required_numeric:
            value = _safe_float(row.get(field))
            if value is None or not math.isfinite(value):
                row_errors.append(f"{field} 不是有限数值")
            elif field != "spread_margin_cny_raw" and value < 0:
                row_errors.append(f"{field} 不是合法非负数")
        release_date = row.get("release_date")
        if release_date is not None and as_of_date is not None and release_date > as_of_date:
            row_errors.append("release_date 晚于 as_of_date")
        if row_errors:
            errors.extend(f"{label}: {message}" for message in row_errors)
        else:
            valid_indices.append(index)
    return tuple(valid_indices), tuple(errors)


def validate_spread_raw_frame(
    frame: pl.DataFrame,
    *,
    as_of_date: date | None = None,
) -> tuple[str, ...]:
    """返回价差 RAW 的质量问题，不修改源帧。"""
    _valid_indices, errors = validate_spread_raw_rows(frame, as_of_date=as_of_date)
    return errors


def validate_spot_price_records(
    records: Iterable[ChemicalSpotPriceRecord],
    *,
    as_of_date: date | None = None,
) -> tuple[list[ChemicalSpotPriceRecord], tuple[str, ...]]:
    """校验现货出厂基准价记录：结构、数值与同品种日期单调性。

    拒绝负值/非有限价格、缺失符号或日期、重复 (symbol, trade_date) 以及
    同品种内日期未严格递增的记录；``as_of_date`` 仅在调用方明确提供时用于
    检查 release_date，避免把报告期末错误当成信息可得日。
    """
    valid: list[ChemicalSpotPriceRecord] = []
    errors: list[str] = []
    seen: set[tuple[str, date]] = set()
    prev_date_by_symbol: dict[str, date] = {}

    for record in records:
        prefix = f"{record.symbol}:{record.trade_date}"
        record_errors: list[str] = []
        if not str(record.symbol or "").strip() or not str(record.product_name or "").strip():
            record_errors.append("symbol/product_name 缺失")
        if record.trade_date is None:
            record_errors.append("trade_date 缺失")
        price = record.spot_price_cny
        if price is None or not math.isfinite(price) or price < 0:
            record_errors.append(f"spot_price_cny={price!r} 不是合法非负数")
        if (
            record.release_date is not None
            and as_of_date is not None
            and record.release_date > as_of_date
        ):
            record_errors.append("release_date 晚于 as_of_date")

        if record.trade_date is not None:
            key = (record.symbol, record.trade_date)
            if key in seen:
                record_errors.append("重复 (symbol, trade_date)")
            seen.add(key)
            prev = prev_date_by_symbol.get(record.symbol)
            if prev is not None and record.trade_date <= prev:
                record_errors.append(f"trade_date 未严格递增 (<= {prev})")
            prev_date_by_symbol[record.symbol] = record.trade_date

        if record_errors:
            errors.extend(f"{prefix}: {message}" for message in record_errors)
        else:
            valid.append(record)

    return valid, tuple(errors)


def _safe_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


__all__ = [
    "validate_capacity_raw_frame",
    "validate_chemical_market_records",
    "validate_spot_price_records",
    "validate_spread_raw_frame",
    "validate_spread_raw_rows",
]
