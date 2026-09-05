"""国家统计局月度公开接口响应解析器。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _safe_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "…", "...", "null", "None"}:
        return None
    try:
        return float(text.rstrip("%"))
    except ValueError:
        return None


def _month_from_text(value: object) -> str | None:
    text = str(value or "")
    match = re.search(r"(20\d{2})\s*[年/-]\s*(\d{1,2})\s*(?:月)?", text)
    if match is None:
        match = re.search(r"(20\d{2})(\d{2})", text)
    if match is None:
        return None
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def _walk_mappings(value: object) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for child in value.values():
            found.extend(_walk_mappings(child))
    elif isinstance(value, list | tuple):
        for child in value:
            found.extend(_walk_mappings(child))
    return found


def _value_from_mapping(row: Mapping[str, Any]) -> float | None:
    for key in ("value", "val", "data", "valuecode", "数值", "本期", "本月", "当月"):
        candidate = row.get(key)
        if isinstance(candidate, Mapping):
            candidate = candidate.get("data") or candidate.get("value")
        parsed = _safe_float(candidate)
        if parsed is not None:
            return parsed
    return None


def _indicator_field(label: str) -> str | None:
    normalized = label.lower().replace(" ", "")
    if any(token in normalized for token in ("累计增长", "累计同比", "累计增速")):
        return "output_cum_yoy"
    if any(token in normalized for token in ("同比增长", "同比增减", "同比")):
        return "output_yoy"
    if any(token in normalized for token in ("累计值", "本期累计", "本年累计")):
        return "output_cumulative"
    if any(token in normalized for token in ("当期值", "本期值", "当期", "本期", "本月", "当月")):
        return "output_current"
    return None


def parse_nbs_solar_cell_response_rows(
    payload: object,
    *,
    source_url: str,
) -> list[dict[str, Any]]:
    """解析 NBS 新站 ``stream/esData`` 返回的多月份记录。"""
    if isinstance(payload, Mapping):
        raw_periods = payload.get("data")
        period_items = raw_periods if isinstance(raw_periods, list) else [payload]
    else:
        period_items = [payload]
    parsed_rows: list[dict[str, Any]] = []
    for period_item in period_items:
        if not isinstance(period_item, Mapping):
            continue
        period = _month_from_text(
            period_item.get("name") or period_item.get("code") or period_item.get("report_month")
        )
        if period is None:
            continue
        values: dict[str, float] = {}
        raw_values: dict[str, str] = {}
        raw_indicators = period_item.get("values")
        if not isinstance(raw_indicators, list):
            raw_indicators = [period_item]
        for indicator in raw_indicators:
            if not isinstance(indicator, Mapping):
                continue
            label = " ".join(
                str(indicator.get(key) or "")
                for key in ("i_showname", "ek_dp_name", "dp_name", "name", "label")
            )
            field = _indicator_field(label)
            number = _safe_float(indicator.get("value"))
            if field is None or number is None:
                continue
            values[field] = number
            raw_values[field] = str(indicator.get("value"))
        if not values:
            continue
        parsed_rows.append(
            {
                "report_month": period,
                **values,
                "output_current_raw": raw_values.get("output_current"),
                "output_cumulative_raw": raw_values.get("output_cumulative"),
                "output_yoy_raw": raw_values.get("output_yoy"),
                "output_cum_yoy_raw": raw_values.get("output_cum_yoy"),
                "unit": "ten_thousand_kw",
                "source": "NBS",
                "source_url": source_url,
            }
        )
    return parsed_rows


def parse_nbs_solar_cell_response(
    payload: object,
    report_month: str,
    *,
    source_url: str,
) -> dict[str, Any] | None:
    """兼容 NBS ``QueryData`` 与公开发布接口的太阳能电池响应结构。

    NBS 两套公开接口的外层字段并不稳定，但数据节点都包含指标名称、报告期和数值。
    解析器只负责保留源端数值，不在这里计算同比、累计或单位换算。
    """
    structured_rows = parse_nbs_solar_cell_response_rows(payload, source_url=source_url)
    exact = next(
        (row for row in structured_rows if row.get("report_month") == report_month),
        None,
    )
    if exact is not None:
        return exact

    rows = _walk_mappings(payload)
    values: dict[str, float] = {}
    unit = "ten_thousand_kw"
    detected_month = report_month

    aliases = {
        "output_current": (
            "output_current",
            "current",
            "当期值",
            "本期值",
            "本月",
            "当月",
            "本期",
        ),
        "output_cum_yoy": ("累计同比", "累计增长", "累计增速", "本年累计同比"),
        "output_cumulative": (
            "output_cumulative",
            "cumulative",
            "累计值",
            "累计",
            "本期累计",
            "本年累计",
        ),
        "output_yoy": ("output_yoy", "yoy", "同比增长", "同比"),
    }

    for row in rows:
        row_text = " ".join(
            str(row.get(key, ""))
            for key in (
                "name",
                "label",
                "title",
                "zbmc",
                "i_showname",
                "ek_dp_name",
                "dp_name",
                "value",
            )
        )
        detected_month = (
            _month_from_text(
                row.get("report_month")
                or row.get("month")
                or row.get("sj")
                or row.get("period")
                or row.get("date")
                or row.get("name")
                or row.get("code")
            )
            or detected_month
        )
        unit_candidate = row.get("unit") or row.get("dw") or row.get("unitName")
        if unit_candidate:
            unit = str(unit_candidate)
        number = _value_from_mapping(row)
        if number is None:
            continue
        normalized = row_text.lower().replace(" ", "")
        for field, field_aliases in aliases.items():
            if any(alias.lower().replace(" ", "") in normalized for alias in field_aliases):
                # “累计同比”必须优先于“同比”，否则会覆盖为单月同比。
                if field in {"output_yoy", "output_cumulative"} and (
                    "累计同比" in normalized or "累计增长" in normalized
                ):
                    continue
                values[field] = number
                break

    # 直接键值格式是测试夹具和部分公开接口常用的返回形态。
    direct_rows = _walk_mappings(payload)
    for row in direct_rows:
        for field in aliases:
            if field in row:
                parsed = _safe_float(row[field])
                if parsed is not None:
                    values[field] = parsed
        direct_month = _month_from_text(row.get("report_month") or row.get("month"))
        if direct_month:
            detected_month = direct_month
        if row.get("unit"):
            unit = str(row["unit"])

    if not values:
        return None
    return {
        "report_month": detected_month,
        **values,
        "unit": unit,
        "source": "NBS",
        "source_url": source_url,
    }


__all__ = ["parse_nbs_solar_cell_response"]
