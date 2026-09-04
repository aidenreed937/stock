"""晶圆代工产能利用率公告 RAW 解析器。"""

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

DEFAULT_SMIC_BASE_URL = "https://www.smics.com"
DEFAULT_SMIC_FINANCIAL_SUMMARY_URL = (
    "https://www.smics.com/en/site/company_financialSummary?year={year}"
)
logger = logging.getLogger(__name__)

_CHINESE_YEAR_MAP = {
    "零": "0",
    "〇": "0",
    "○": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}

_QUARTER_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}


def parse_smic_operating_text(
    text: str,
    default_quarter: str | None = None,
    default_date: date | None = None,
) -> dict[str, Any] | None:
    """从中芯国际季度业绩公报文本解析产能利用率、月产能与出货量。"""
    if not text:
        return None
    if not re.search(
        r"截至[\s\S]{0,120}?止\s*三\s*[个個亇]?\s*月|"
        r"(?:three|3)\s+months?\s+ended",
        text,
        re.IGNORECASE,
    ):
        return None

    quarter = _extract_smic_report_quarter(text) or default_quarter
    utilization_raw = _extract_smic_utilization_raw(text)
    utilization = _parse_numeric_raw(utilization_raw)
    if not quarter or utilization is None:
        return None

    yr = int(quarter[:4])
    q_idx = int(quarter[-1])
    m_end = q_idx * 3
    d_end = 31 if m_end in (3, 12) else 30
    trade_date = date(yr, m_end, d_end)
    release_date = _extract_smic_release_date(text, trade_date) or default_date
    if release_date is None:
        return None

    return {
        "report_quarter": quarter,
        "trade_date": trade_date,
        "smic_utilization_pct": utilization,
        "smic_monthly_capacity_8inch_kw": _extract_smic_monthly_capacity(text),
        "smic_wafer_shipment_kw": _extract_smic_wafer_shipment(text),
        "smic_utilization_raw": utilization_raw,
        "smic_monthly_capacity_raw": _extract_smic_monthly_capacity_raw(text),
        "smic_wafer_shipment_raw": _extract_smic_wafer_shipment_raw(text),
        "release_date": release_date,
    }


def parse_smic_operating_pdf_bytes(
    pdf_bytes: bytes,
    default_quarter: str | None = None,
    default_date: date | None = None,
) -> dict[str, Any] | None:
    """从中芯国际官方 PDF 快照提取文本后复用公告解析规则。"""
    if not pdf_bytes:
        return None
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 SMIC PDF 失败: %s", exc)
        return None
    return parse_smic_operating_text(
        text,
        default_quarter=default_quarter,
        default_date=default_date,
    )


def extract_smic_announcement_links(
    html_content: bytes | str,
    base_url: str = DEFAULT_SMIC_BASE_URL,
) -> list[str]:
    """从中芯国际新闻列表页解析季度业绩公告链接。"""
    return [url for url, _release_date in extract_smic_announcement_targets(html_content, base_url)]


def extract_smic_announcement_targets(
    html_content: bytes | str,
    base_url: str = DEFAULT_SMIC_BASE_URL,
) -> list[tuple[str, date | None]]:
    """从中芯国际新闻列表页解析公告链接及列表显示的发布日期。"""
    soup = BeautifulSoup(html_content, "html.parser")
    targets: list[tuple[str, date | None]] = []
    for a_tag in soup.find_all("a", href=True):
        if not isinstance(a_tag, Tag):
            continue
        title = a_tag.get_text(strip=True)
        title_lower = title.lower()
        if not any(
            kw in title_lower
            for kw in ["业绩公布", "季度业绩", "财报", "财务报告", "results announcement"]
        ):
            continue
        href = a_tag.get("href")
        if isinstance(href, str):
            row = a_tag.find_parent("tr")
            row_text = row.get_text(" ", strip=True) if isinstance(row, Tag) else ""
            targets.append(
                (
                    urllib.parse.urljoin(base_url, href),
                    _parse_smic_date(row_text),
                )
            )
    return targets


def extract_smic_financial_report_links(
    html_content: bytes | str,
    base_url: str = DEFAULT_SMIC_BASE_URL,
) -> list[str]:
    """从 SMIC 官方财务摘要页提取 Earnings Release PDF 链接。"""
    soup = BeautifulSoup(html_content, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        href = href.strip()
        context = anchor.get_text(" ", strip=True).lower()
        if not href.lower().endswith(".pdf") or "earnings release" not in context:
            continue
        url = urllib.parse.urljoin(base_url, href)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _extract_smic_report_quarter(text: str) -> str | None:
    english_ended_match = re.search(
        r"(?:three|3)\s+months?\s+ended\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+"
        r"(?P<day>\d{1,2}),?\s*(?P<year>20\s*\d\s*\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if english_ended_match:
        month = _english_month_number(english_ended_match.group("month"))
        if month is not None:
            year_value = int(re.sub(r"\s+", "", english_ended_match.group("year")))
            return f"{year_value:04d}Q{(month - 1) // 3 + 1}"

    ch_match = re.search(
        r"([零〇○一二三四五六七八九]{4})\s*年?\s*第?([一二三四1-4])\s*季(?:度)?",
        text,
    )
    if ch_match:
        ch_yr, ch_q = ch_match.groups()
        yr_str = "".join(_CHINESE_YEAR_MAP.get(c, c) for c in ch_yr)
        q_idx = _QUARTER_MAP.get(ch_q, 1)
        return f"{yr_str}Q{q_idx}"

    q_match = re.search(r"(\d{4})年?\s*(?:第([一二三四1-4])季|Q([1-4]))", text)
    if q_match:
        yr_str, ch_q, num_q = q_match.groups()
        q_idx = _QUARTER_MAP.get(ch_q) or (int(num_q) if num_q else 1)
        return f"{yr_str}Q{q_idx}"

    compact_match = re.search(r"\b([1-4])\s*Q\s*(20\s*\d\s*\d{2}|\d\s*\d)\b", text, re.IGNORECASE)
    if compact_match:
        compact_q, compact_year = compact_match.groups()
        compact_year = re.sub(r"\s+", "", compact_year)
        full_year = compact_year if len(compact_year) == 4 else f"20{compact_year}"
        return f"{full_year}Q{int(compact_q)}"

    english_match = re.search(
        r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\s+(20\d{2})\b|"
        r"\b(20\d{2})\s+(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b",
        text,
        re.IGNORECASE,
    )
    if english_match:
        leading_q, leading_year, trailing_year, trailing_q = english_match.groups()
        quarter_name = leading_q or trailing_q
        year_text = leading_year or trailing_year
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
        return f"{year_text}Q{q_idx}"

    period_match = re.search(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*\d{1,2}\s*日|"
        r"([零〇○一二三四五六七八九]{4})\s*年\s*"
        r"([一二三四五六七八九十]{1,3})\s*月",
        text,
    )
    if period_match:
        numeric_year, numeric_month, chinese_year, chinese_month = period_match.groups()
        if numeric_year and numeric_month:
            year = int(numeric_year)
            month = int(numeric_month)
        elif chinese_year and chinese_month:
            year = int("".join(_CHINESE_YEAR_MAP[char] for char in chinese_year))
            month = _parse_chinese_month(chinese_month)
        else:
            return None
        if 1 <= month <= 12:
            return f"{year:04d}Q{(month - 1) // 3 + 1}"

    english_period = re.search(
        r"\b(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+(?P<year>20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if english_period:
        english_month = _english_month_number(english_period.group("month"))
        if english_month is not None:
            return f"{int(english_period.group('year')):04d}Q{(english_month - 1) // 3 + 1}"
    return None


def _english_month_number(value: str) -> int | None:
    months = {
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
    return months.get(value.lower())


def _parse_chinese_month(value: str) -> int:
    if value.isdigit():
        return int(value)
    if "十" not in value:
        return int(_CHINESE_YEAR_MAP.get(value, "0"))

    tens_raw, _, ones_raw = value.partition("十")
    tens = int(_CHINESE_YEAR_MAP.get(tens_raw, "1")) if tens_raw else 1
    ones = int(_CHINESE_YEAR_MAP.get(ones_raw, "0")) if ones_raw else 0
    return tens * 10 + ones


def _extract_smic_utilization(text: str) -> float | None:
    return _parse_numeric_raw(_extract_smic_utilization_raw(text))


def _extract_smic_utilization_raw(text: str) -> str | None:
    match = re.search(
        r"(?:產能利用率|产能利用率|capacity utilization rate|utilization rate)"
        r"\s*\(\d+\)[\s\S]{0,80}?(\d{1,3}(?:\.\d+)?\s*%)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r"(?:產能利用率|产能利用率|capacity utilization rate|utilization rate)[^\d%]{0,15}"
            r"(\d{1,3}(?:\.\d+)?\s*%)",
            text,
            re.IGNORECASE,
        )
    return match.group(1).strip() if match else None


def _extract_smic_monthly_capacity(text: str) -> float | None:
    return _parse_wafer_k_raw(_extract_smic_monthly_capacity_raw(text))


def _extract_smic_monthly_capacity_raw(text: str) -> str | None:
    direct_patterns = (
        r"(?:monthly\s+cap\s*ac\s*ity)\s+[\s\S]{0,60}?"
        r"in\s*creased\s+t\s*o\s*"
        r"([0-9][\d,]*(?:\.\d+)?\s*(?:thousand|million|k|wafers?)?)",
        r"(?:月[產产]能|[產产]能(?!利用率))[^。\n]{0,180}?"
        r"(?:增加至|增加到|上升至|至)\s*"
        r"(?:[^。\n]*?的)?\s*([0-9][\d,]*(?:\.\d+)?\s*(?:千片|k|片))",
    )
    for pattern in direct_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    match = re.search(
        r"(?:monthly\s+cap\s*ac\s*ity)[^\d]{0,80}?"
        r"([0-9][\d,]*(?:\.\d+)?\s*(?:thousand|million|k))",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(
        r"(?:monthly\s+cap\s*ac\s*ity)[^\d]{0,100}?([0-9][\d,]*(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(
        r"(?:月[產产]能|[產产]能(?!利用率))[^。\n]{0,120}?"
        r"([0-9][\d,]*(?:\.\d+)?\s*(?:千片|k|片|thousand|million|wafers?))",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _extract_smic_wafer_shipment(text: str) -> float | None:
    return _parse_wafer_k_raw(_extract_smic_wafer_shipment_raw(text))


def _extract_smic_wafer_shipment_raw(text: str) -> str | None:
    heading_matches = list(re.finditer(r"shipment\s+and\s+utilization", text, re.IGNORECASE))
    for heading in heading_matches:
        section = text[heading.end() : heading.end() + 1200]
        label = re.search(r"\bwafer[s]?\s+ship(?:ped|ments?)\b", section, re.IGNORECASE)
        if label:
            value = _first_value_after_label(section, label.end())
            if value:
                return value

    labels = re.finditer(
        r"(?:晶圓出貨量|晶圆出货量|銷售晶圓|销售晶圆|wafer\s+shipments?|sales\s+wafers?)",
        text,
        re.IGNORECASE,
    )
    for label in labels:
        value = _first_value_after_label(text, label.end())
        if value:
            has_unit = re.search(r"千片|k|equivalent\s+wafers?|wafers?", value, re.IGNORECASE)
            numeric = _parse_numeric_raw(value)
            if has_unit or (numeric is not None and numeric >= 100.0):
                return value
    return None


def _first_value_after_label(text: str, label_end: int) -> str | None:
    tail = text[label_end : label_end + 180]
    while True:
        stripped = tail.lstrip()
        if not stripped.startswith("("):
            tail = stripped
            break
        closing = stripped.find(")")
        if closing < 0:
            tail = stripped
            break
        tail = stripped[closing + 1 :]

    match = re.search(
        r"([0-9][\d,]*(?:\.\d+)?\s*(?:千片|k|片|thousand|million|wafers?)?)",
        tail,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _parse_numeric_raw(raw_value: str | None) -> float | None:
    if raw_value is None:
        return None
    numeric = re.sub(r"[^\d.-]", "", raw_value)
    if not numeric:
        return None
    return float(numeric)


def _parse_wafer_k_raw(raw_value: str | None) -> float | None:
    """将片数原文统一为千片，区分千片、百万片和单片口径。"""
    if raw_value is None:
        return None
    match = re.search(r"[-+]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)", raw_value)
    if match is None:
        return None
    value = float(match.group(0).replace(",", ""))
    lower = raw_value.lower()
    if "million" in lower or "百万" in lower:
        return value * 1000.0
    if (
        "thousand" in lower
        or "千" in lower
        or re.search(r"\bk(?:pcs?|w)?\b", lower)
        or "kpcs" in lower
    ):
        return value
    return value / 1000.0


def _extract_smic_release_date(text: str, report_date: date) -> date | None:
    """从公告正文提取报告期之后最近的公告日期。"""
    candidates: set[date] = set()
    patterns = (
        r"\b(20\d\d)\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\b",
        r"\b([零〇○一二三四五六七八九]{4})\s*年\s*"
        r"([一二三四五六七八九十百零〇○]{1,3})\s*月\s*"
        r"([一二三四五六七八九十百零〇○]{1,3})\s*日\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            try:
                year_raw, month_raw, day_raw = match.groups()
                year = (
                    int(year_raw)
                    if year_raw.isdigit()
                    else int("".join(_CHINESE_YEAR_MAP[char] for char in year_raw))
                )
                month = int(month_raw) if month_raw.isdigit() else _parse_chinese_month(month_raw)
                day = int(day_raw) if day_raw.isdigit() else _parse_chinese_month(day_raw)
                candidates.add(date(year, month, day))
            except ValueError:
                continue

    english_pattern = re.compile(
        r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|"
        r"November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\b",
        re.IGNORECASE,
    )
    for match in english_pattern.finditer(text):
        try:
            month = {
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
            }[match.group("month").lower()]
            candidates.add(date(int(match.group("year")), month, int(match.group("day"))))
        except ValueError:
            continue

    later_dates = sorted(candidate for candidate in candidates if candidate > report_date)
    return later_dates[0] if later_dates else None


def _parse_smic_date(text: str) -> date | None:
    """解析新闻列表行中的 ISO/中文公告日期。"""
    match = re.search(r"\b(20\d\d)[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if match is None:
        match = re.search(r"\b(20\d\d)年\s*(\d{1,2})月\s*(\d{1,2})日?\b", text)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
