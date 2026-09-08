"""CPCA 乘用车产销数据解析器。"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import now_utc_iso

CPCA_BASE_URL = "http://www.cpcaauto.com"
CPCA_FUEL_MARKET_URL = "http://data.cpcadata.com/FuelMarket"


def parse_matrix_file(path: Path) -> dict[str, float]:
    """从 CPCA 二维宽表矩阵中解析月度时序字典。"""
    result: dict[str, float] = {}
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        year_cols = [
            column
            for column in (reader.fieldnames or [])
            if column != "month" and column.strip().replace("年", "").isdigit()
        ]
        for row in reader:
            month_raw = str(row.get("month", "")).strip().replace("月", "")
            try:
                month = int(month_raw)
            except ValueError:
                continue
            for year_col in year_cols:
                value = row.get(year_col)
                if value is None or str(value).strip() in ("", "nan", "None"):
                    continue
                try:
                    number = float(str(value).strip())
                    if number > 0:
                        year = int(year_col.replace("年", ""))
                        result[f"{year:04d}-{month:02d}"] = round(number, 4)
                except (ValueError, TypeError):
                    continue
    return result


def parse_cpca_bulletin_article(
    text: str,
    source_url: str = "",
    report_month_hint: str | None = None,
) -> dict[str, Any] | None:
    """从 CPCA 月报正文中提取新能源零售、出口与批发数据。"""
    clean_text = text.replace(" ", "").replace("\r", "")
    if "新能源" not in clean_text:
        return None
    month_match = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)",
        clean_text,
    )
    if not month_match:
        return None
    report_month = report_month_hint or (
        f"{int(month_match.group(1)):04d}-{int(month_match.group(2)):02d}"
    )
    wholesale_match = re.search(
        r"新能源(?:乘用车)?批发(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆", clean_text
    )
    retail_match = re.search(
        r"新能源(?:乘用车)?(?:国内)?零售(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆",
        clean_text,
    ) or re.search(
        r"新能源市场销量(?:约)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆",
        clean_text,
    )
    export_match = re.search(
        r"新能源(?:乘用车)?出口(?:销量)?(?:达到|为)?\s*(\d+\.?\d*)\s*万辆",
        clean_text,
    )
    penetration_match = re.search(
        r"(?:零售|批发)?渗透率(?:达到|为)?\s*(\d+\.?\d*)%", clean_text
    ) or re.search(r"新能源市场[^。；]{0,30}占[^\d]*(\d+\.?\d*)%", clean_text)
    if wholesale_match is None and retail_match is None and export_match is None:
        return None
    return {
        "report_month": report_month,
        "release_date": _extract_release_date(clean_text),
        "wholesale_volume_ten_thousand": _match_float(wholesale_match),
        "wholesale_volume_raw": _match_raw(wholesale_match),
        "retail_volume_ten_thousand": _match_float(retail_match),
        "retail_volume_raw": _match_raw(retail_match),
        "export_volume_ten_thousand": _match_float(export_match),
        "export_volume_raw": _match_raw(export_match),
        "penetration_rate": (
            round(float(penetration_match.group(1)) / 100.0, 4) if penetration_match else None
        ),
        "penetration_rate_raw": f"{penetration_match.group(1)}%" if penetration_match else None,
        "source": "CPCA",
        "source_url": source_url or f"{CPCA_BASE_URL}/",
        "collected_at": now_utc_iso(),
    }


def parse_cpca_snapshot(content: str, path: Path) -> list[dict[str, Any]]:
    """解析 CPCA 官方 JSON 快照或历史兼容 JSON 记录。"""
    if path.suffix not in {".json", ".gz"}:
        return []
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("records", [])
        if not items and "fuel_market" in payload:
            return _parse_source_payload(payload)
    else:
        return []
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("report_month"):
            continue
        result.append(
            {
                **item,
                "source": item.get("source") or "CPCA",
                "source_url": item.get("source_url") or f"{CPCA_BASE_URL}/",
            }
        )
    return result


def _parse_source_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fuel_map = _snapshot_matrix(payload.get("fuel_market"))
    wholesale_map = _snapshot_matrix(payload.get("total_market_wholesale"))
    retail_map = _snapshot_matrix(payload.get("total_market_retail"))
    export_map = _snapshot_matrix(payload.get("total_market_export"))
    result: list[dict[str, Any]] = []
    for report_month in sorted(fuel_map):
        wholesale, wholesale_raw = fuel_map[report_month]
        total_item = wholesale_map.get(report_month)
        retail_item = retail_map.get(report_month)
        export_item = export_map.get(report_month)
        total = total_item[0] if total_item else None
        penetration = round(wholesale / total, 4) if total and total > 0 else None
        result.append(
            {
                "report_month": report_month,
                "wholesale_volume_ten_thousand": wholesale,
                "wholesale_volume_raw": wholesale_raw,
                "total_volume_ten_thousand": total,
                "total_volume_raw": total_item[1] if total_item else None,
                "retail_volume_ten_thousand": retail_item[0] if retail_item else None,
                "retail_volume_raw": retail_item[1] if retail_item else None,
                "export_volume_ten_thousand": export_item[0] if export_item else None,
                "export_volume_raw": export_item[1] if export_item else None,
                "penetration_rate": penetration,
                "penetration_rate_raw": str(penetration) if penetration is not None else None,
                "source": "CPCA",
                "source_url": CPCA_FUEL_MARKET_URL,
                "data_status": "actual",
                "collected_at": str(payload.get("collected_at") or now_utc_iso()),
            }
        )
    return result


def _snapshot_matrix(rows: Any) -> dict[str, tuple[float, str]]:
    if not isinstance(rows, list):
        return {}
    result: dict[str, tuple[float, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        month_raw = str(row.get("月份", row.get("month", ""))).strip().replace("月", "")
        try:
            month = int(month_raw)
        except ValueError:
            continue
        for key, raw_value in row.items():
            if "年" not in str(key):
                continue
            value_raw = str(raw_value).strip()
            if value_raw in ("", "nan", "None"):
                continue
            try:
                value = float(value_raw)
                year = int(str(key).replace("年", ""))
            except (TypeError, ValueError):
                continue
            if value > 0:
                result[f"{year:04d}-{month:02d}"] = (round(value, 4), value_raw)
    return result


def _extract_release_date(text: str) -> date | None:
    match = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _match_float(match: re.Match[str] | None) -> float | None:
    return round(float(match.group(1)), 4) if match else None


def _match_raw(match: re.Match[str] | None) -> str | None:
    return match.group(0) if match else None


__all__ = [
    "CPCA_BASE_URL",
    "CPCA_FUEL_MARKET_URL",
    "parse_cpca_bulletin_article",
    "parse_cpca_snapshot",
    "parse_matrix_file",
]
