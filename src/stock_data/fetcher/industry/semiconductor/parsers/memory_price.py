"""TrendForce DRAM/NAND 价格 HTML 解析器。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

_HEADER_MAP = {
    "item": "item_raw",
    "daily high": "daily_high_raw",
    "daily low": "daily_low_raw",
    "session high": "session_high_raw",
    "session low": "session_low_raw",
    "session average": "session_average_raw",
    "high": "high_raw",
    "low": "low_raw",
    "average": "average_raw",
    "session change": "session_change_raw",
    "average change": "average_change_raw",
    "low change": "low_change_raw",
}


def parse_trendforce_memory_price_html(
    html_text: str,
    *,
    product_family: str,
    price_scope: str,
    page_slug: str,
    source_url: str,
    collected_at: str,
    raw_content_hash: str,
    raw_snapshot_path: str,
) -> list[dict[str, Any]]:
    """从 TrendForce 价格页抽取当前公开价格表源端字段。"""
    soup = BeautifulSoup(html_text, "html.parser")
    updated_at_raw = _extract_last_update_text(soup)
    release_date = _parse_update_date(updated_at_raw)
    rows: list[dict[str, Any]] = []

    for table_index, table in enumerate(soup.find_all("table")):
        if not isinstance(table, Tag):
            continue
        parsed_rows = _parse_table_rows(table)
        if not parsed_rows:
            continue
        table_title = _table_title(table)
        for parsed in parsed_rows:
            item_raw = str(parsed.get("item_raw") or "").strip()
            if not item_raw:
                continue
            rows.append(
                {
                    "trade_date": release_date,
                    "updated_at_raw": updated_at_raw,
                    "product_family": product_family.upper(),
                    "price_scope": price_scope,
                    "page_slug": page_slug,
                    "table_index": table_index,
                    "table_title": table_title,
                    "item_raw": item_raw,
                    "daily_high_raw": parsed.get("daily_high_raw"),
                    "daily_low_raw": parsed.get("daily_low_raw"),
                    "session_high_raw": parsed.get("session_high_raw"),
                    "session_low_raw": parsed.get("session_low_raw"),
                    "session_average_raw": parsed.get("session_average_raw"),
                    "high_raw": parsed.get("high_raw"),
                    "low_raw": parsed.get("low_raw"),
                    "average_raw": parsed.get("average_raw"),
                    "session_change_raw": parsed.get("session_change_raw"),
                    "average_change_raw": parsed.get("average_change_raw"),
                    "low_change_raw": parsed.get("low_change_raw"),
                    "source": "TrendForce",
                    "source_url": source_url,
                    "release_date": release_date,
                    "data_status": "actual",
                    "collected_at": collected_at,
                    "raw_content_sha256": raw_content_hash,
                    "raw_snapshot_path": raw_snapshot_path,
                }
            )

    return rows


def _parse_table_rows(table: Tag) -> list[dict[str, str | None]]:
    trs = [tr for tr in table.find_all("tr") if isinstance(tr, Tag)]
    if not trs:
        return []

    header_cells = _row_cells(trs[0])
    header_keys = [_normalise_header(cell) for cell in header_cells]
    if "item_raw" not in header_keys:
        return []

    rows: list[dict[str, str | None]] = []
    for tr in trs[1:]:
        cells = _row_cells(tr)
        if not cells or len(cells) < 2:
            continue
        mapped: dict[str, str | None] = {}
        for index, key in enumerate(header_keys):
            if not key or index >= len(cells):
                continue
            mapped[key] = _source_text(cells[index])
        if mapped.get("item_raw"):
            rows.append(mapped)
    return rows


def _row_cells(tr: Tag) -> list[str]:
    return [
        cell.get_text(" ", strip=True).replace("\xa0", " ").strip()
        for cell in tr.find_all(["th", "td"])
    ]


def _normalise_header(header: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", header.replace("\xa0", " ")).strip().lower()
    return _HEADER_MAP.get(cleaned)


def _extract_last_update_text(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ", strip=True)
    match = re.search(
        r"Last\s+Update\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*\([^)]*\))",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match = re.search(r"Last\s+Update\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _parse_update_date(updated_at_raw: str) -> date | None:
    match = re.search(r"(20\d\d-\d{2}-\d{2})", updated_at_raw)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _table_title(table: Tag) -> str:
    for previous in table.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "a", "div", "span"],
        limit=20,
    ):
        if not isinstance(previous, Tag):
            continue
        text = str(previous.get_text(" ", strip=True)).replace("\xa0", " ").strip()
        if _looks_like_title(text):
            return text
    return ""


def _looks_like_title(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    lowered = text.lower()
    if "history" in lowered or "last update" in lowered:
        return False
    return any(token in lowered for token in ("dram", "nand", "flash", "wafer", "price"))


def _source_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
