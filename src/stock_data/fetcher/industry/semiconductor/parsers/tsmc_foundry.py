"""TSMC 季度管理报告的晶圆出货与利用率 RAW 解析器。"""

from __future__ import annotations

import io
import logging
import re
import urllib.parse
from datetime import date
from typing import Any

import pypdf
from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)

DEFAULT_TSMC_QUARTERLY_URL = "https://investor.tsmc.com/english/quarterly-results"

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_tsmc_quarterly_report_text(
    text: str,
    default_quarter: str | None = None,
    default_date: date | None = None,
) -> dict[str, Any] | None:
    """从 TSMC 官方季度管理报告文本解析出货量和可用的利用率。"""
    if not text:
        return None

    quarter = _extract_tsmc_report_quarter(text) or _normalise_quarter(default_quarter)
    if quarter is None:
        return None

    trade_date = _quarter_end(quarter)
    release_date = _extract_tsmc_release_date(text, trade_date) or default_date
    if release_date is None:
        return None

    utilization_raw = _extract_tsmc_utilization_raw(text)
    shipment_raw = _extract_tsmc_wafer_shipments_raw(text)
    capacity_raw = _extract_tsmc_capacity_raw(text)
    if utilization_raw is None and shipment_raw is None and capacity_raw is None:
        return None

    status = "reported" if utilization_raw is not None else "unavailable"
    if utilization_raw is None and shipment_raw is not None and capacity_raw is not None:
        status = "derived"

    return {
        "report_quarter": quarter,
        "trade_date": trade_date,
        "tsmc_utilization_raw": utilization_raw,
        "tsmc_wafer_shipments_12in_kpcs_raw": shipment_raw,
        "tsmc_capacity_12in_kpcs_raw": capacity_raw,
        "tsmc_utilization_status": status,
        "release_date": release_date,
    }


def parse_tsmc_quarterly_report_pdf_bytes(
    pdf_bytes: bytes,
    default_quarter: str | None = None,
    default_date: date | None = None,
) -> dict[str, Any] | None:
    """从 TSMC 官方季度管理报告 PDF 字节流提取文本并解析。"""
    if not pdf_bytes:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 TSMC 季度管理报告 PDF 失败: %s", exc)
        text = pdf_bytes.decode("utf-8", errors="ignore")
    return parse_tsmc_quarterly_report_text(
        text,
        default_quarter=default_quarter,
        default_date=default_date,
    )


def extract_tsmc_quarterly_report_links(
    html_content: bytes | str,
    base_url: str = DEFAULT_TSMC_QUARTERLY_URL,
) -> list[str]:
    """从 TSMC 季度结果页面提取管理报告 PDF 链接。"""
    if isinstance(html_content, bytes):
        html_text = html_content.decode("utf-8", errors="ignore")
    else:
        html_text = html_content

    soup = BeautifulSoup(html_text, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        href = href.replace("\\/", "/")
        decoded_href = urllib.parse.unquote(href).lower()
        parent = anchor.find_parent(["li", "td", "div", "section"])
        context = parent.get_text(" ", strip=True) if isinstance(parent, Tag) else ""
        search_text = f"{decoded_href} {anchor.get_text(' ', strip=True).lower()} {context.lower()}"
        if ".pdf" not in decoded_href:
            continue
        if "management" not in search_text:
            continue
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", href)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _extract_tsmc_report_quarter(text: str) -> str | None:
    compact = re.search(r"\b([1-4])\s*Q\s*(20\d{2}|\d{2})\b", text, re.IGNORECASE)
    if compact:
        q_idx, year = compact.groups()
        return f"{year if len(year) == 4 else f'20{year}'}Q{int(q_idx)}"

    named = re.search(
        r"\b(?P<q>first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\s+(?P<year>20\d{2})\b|"
        r"\b(?P<year_after>20\d{2})\s+(?P<q_after>first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b",
        text,
        re.IGNORECASE,
    )
    if named:
        quarter_name = named.group("q") or named.group("q_after")
        year = named.group("year") or named.group("year_after")
        q_idx = {
            "first": 1,
            "1st": 1,
            "second": 2,
            "2nd": 2,
            "third": 3,
            "3rd": 3,
            "fourth": 4,
            "4th": 4,
        }[quarter_name.lower()]
        return f"{year}Q{q_idx}"
    return None


def _normalise_quarter(value: str | None) -> str | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(20\d{2})\s*[- ]?Q\s*([1-4])\s*", value, re.IGNORECASE)
    return f"{match.group(1)}Q{match.group(2)}" if match else None


def _quarter_end(quarter: str) -> date:
    year = int(quarter[:4])
    quarter_index = int(quarter[-1])
    month = quarter_index * 3
    day = 31 if month in (3, 12) else 30
    return date(year, month, day)


def _extract_tsmc_wafer_shipments_raw(text: str) -> str | None:
    match = re.search(
        r"Wafer\s+Shipment\s*\(\s*kpcs\s+12\s+inch[-\s]?equiv\.?\s*\)"
        r"[^\d]{0,60}([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    return f"{match.group(1)} kpcs 12 inch-equiv." if match else None


def _extract_tsmc_utilization_raw(text: str) -> str | None:
    match = re.search(
        r"(?:overall\s+)?capacity\s+utilization\s+rate\s+"
        r"(?:was|is|remained\s+at|increased\s+to|decreased\s+to|rose\s+to|fell\s+to)\s*"
        r"(\d{1,3}(?:\.\d+)?\s*%)",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _extract_tsmc_capacity_raw(text: str) -> str | None:
    """仅接受明确季度口径的产能，避免把年产能除以四伪造成季度产能。"""
    match = re.search(
        r"(?:quarterly|quarter[- ]end|average\s+quarterly)\s+capacity[^\d]{0,40}"
        r"([\d,]+(?:\.\d+)?\s*(?:kpcs|thousand|million))",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _extract_tsmc_release_date(text: str, report_date: date) -> date | None:
    date_pattern = re.compile(
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|"
        r"November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})",
        re.IGNORECASE,
    )
    candidates: list[date] = []
    for match in date_pattern.finditer(text):
        try:
            candidates.append(
                date(
                    int(match.group("year")),
                    _MONTHS[match.group("month").lower()],
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    later = sorted(candidate for candidate in candidates if candidate > report_date)
    return later[0] if later else None
