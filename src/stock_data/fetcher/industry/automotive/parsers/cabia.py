"""CABIA 动力电池月度通报解析器。"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.automotive.paths import AUTOMOTIVE_CABIA_RAW_SUBDIR
from stock_data.fetcher.industry.common import now_utc_iso

CABIA_BASE_URL = "http://www.cabr-ac.com"


def parse_cabia_battery_article(text: str, source_url: str = "") -> dict[str, Any] | None:
    """从 CABIA 通报正文中提取动力电池装车量。"""
    clean_text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html.unescape(text)))
    if "动力电池" not in clean_text and "装车量" not in clean_text and "GWh" not in clean_text:
        return None

    month_match = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)",
        clean_text,
    )
    if not month_match:
        return None
    report_month = f"{int(month_match.group(1)):04d}-{int(month_match.group(2)):02d}"
    release_date = _extract_release_date(clean_text)
    battery_match = re.search(
        r"(?:我国)?动力(?:和储能)?电池装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)",
        clean_text,
    ) or re.search(
        r"装车量(?:共计|达到|为)?\s*(\d+\.?\d*)\s*(?:GWh|吉瓦时|gwh)",
        clean_text,
    )
    if battery_match is None:
        return None

    yoy_match = re.search(
        r"装车量[^\d]*\d+\.?\d*\s*GWh[^\d%]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        clean_text,
    )
    return {
        "report_month": report_month,
        "release_date": release_date,
        "battery_installation_gwh": round(float(battery_match.group(1)), 2),
        "battery_installation_gwh_raw": battery_match.group(0),
        "yoy_growth": round(float(yoy_match.group(1)) / 100.0, 4) if yoy_match else None,
        "yoy_growth_raw": f"{yoy_match.group(1)}%" if yoy_match else None,
        "source": "CABIA",
        "source_url": source_url or f"{CABIA_BASE_URL}/",
        "raw_subdir": AUTOMOTIVE_CABIA_RAW_SUBDIR,
        "collected_at": now_utc_iso(),
    }


def parse_cabia_snapshot(content: str, path: Path) -> list[dict[str, Any]]:
    """解析 CABIA 历史 JSON 快照或财联社快讯快照。"""
    import json

    if path.suffix not in {".json", ".gz"}:
        return []
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []

    items = payload if isinstance(payload, list) else [payload]
    results: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        # 结构化历史快照格式
        if "report_month" in item and "battery_installation_gwh" in item:
            rel_date = None
            if item.get("release_date"):
                try:
                    rel_date = date.fromisoformat(str(item["release_date"]))
                except ValueError:
                    pass
            results.append(
                {
                    "report_month": str(item["report_month"]),
                    "release_date": rel_date,
                    "battery_installation_gwh": float(item["battery_installation_gwh"]),
                    "battery_installation_gwh_raw": str(item["battery_installation_gwh"]),
                    "yoy_growth": float(item["yoy_growth"])
                    if item.get("yoy_growth") is not None
                    else None,
                    "yoy_growth_raw": f"{float(item['yoy_growth']) * 100:.1f}%"
                    if item.get("yoy_growth") is not None
                    else None,
                    "source": str(item.get("source") or "CABIA"),
                    "source_url": str(item.get("source_url") or f"{CABIA_BASE_URL}/"),
                    "raw_subdir": AUTOMOTIVE_CABIA_RAW_SUBDIR,
                    "collected_at": str(item.get("collected_at") or now_utc_iso()),
                }
            )
        # 财联社电报快照格式
        elif "title" in item or "content" in item:
            combined = f"{item.get('title', '')}\n{item.get('content', '')}"
            parsed = parse_cabia_battery_article(
                combined, source_url=str(item.get("source_url") or path.name)
            )
            if parsed:
                results.append(parsed)

    return results


def _extract_release_date(text: str) -> date | None:
    match = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


__all__ = ["CABIA_BASE_URL", "parse_cabia_battery_article", "parse_cabia_snapshot"]
