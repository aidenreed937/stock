"""SEMI WWSEMS 季度设备出货 RAW 解析器。"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

QUARTER_WORDS_MAP = {
    "first quarter": 1,
    "second quarter": 2,
    "third quarter": 3,
    "fourth quarter": 4,
    "q1": 1,
    "q2": 2,
    "q3": 3,
    "q4": 4,
}

_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def parse_semi_article_text(
    text: str,
    source_url: str = "",
    default_date: date | None = None,
) -> dict[str, Any] | None:
    """从 SEMI/PR Newswire 新闻通报文本解析设备出货额与报告季度。"""
    if not text:
        return None

    q_match = re.search(
        r"(first[-\s]+quarter|second[-\s]+quarter|third[-\s]+quarter|fourth[-\s]+quarter|q[1-4])"
        r"\s+(?:of\s+)?(\d{4})",
        text,
        re.IGNORECASE,
    )
    if not q_match:
        return _parse_semi_annual_article_text(
            text,
            source_url=source_url,
            default_date=default_date,
        )

    q_name, year_str = q_match.groups()
    q_num = QUARTER_WORDS_MAP.get(q_name.lower().replace("-", " "))
    if not q_num:
        return None
    year = int(year_str)

    billings_match = re.search(
        r"(?:increased|reached|reach|registered|sales of|billings of|to)\s+"
        r"(?:a\s+record\s+|record\s+)?"
        r"((?:US)?\$[\d\.]+\s*billion)",
        text,
        re.IGNORECASE,
    )
    if not billings_match:
        billings_match = re.search(
            r"(\$[\d\.]+\s*billion)\s+(?:in\s+the\s+)?"
            r"(?:first|second|third|fourth|q[1-4])",
            text,
            re.IGNORECASE,
        )
        if not billings_match:
            return None

    china_match = re.search(
        r"China[^\.\n]*?(?:spending|investments|sales|billings)?[^\.\n]*?"
        r"(\$[\d\.]+\s*billion)",
        text,
        re.IGNORECASE,
    )

    month_end = q_num * 3
    day_end = 31 if month_end in (3, 12) else 30
    trade_date = date(year, month_end, day_end)

    return {
        "report_quarter": f"{year}-Q{q_num}",
        "trade_date": trade_date,
        "source_record_type": "quarterly_actual",
        "report_year": str(year),
        "global_billings_billion_usd": _parse_billion_amount(billings_match.group(1)),
        "china_billings_billion_usd": (
            _parse_billion_amount(china_match.group(1)) if china_match else None
        ),
        "global_billings_raw": billings_match.group(1).strip(),
        "china_billings_raw": china_match.group(1).strip() if china_match else None,
        "annual_billings_raw": None,
        "yoy_growth_raw": _extract_growth_raw(text, "year-over-year"),
        "qoq_growth_raw": _extract_growth_raw(text, "quarter-over-quarter"),
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
    }


def extract_semi_press_release_links(html_content: bytes | str, base_url: str) -> list[str]:
    """从 SEMI/PR Newswire 列表页解析候选 WWSEMS 公报链接。"""
    soup = BeautifulSoup(html_content, "html.parser")
    links: list[str] = []
    for a_tag in soup.find_all("a", href=True):
        if not isinstance(a_tag, Tag):
            continue
        title = a_tag.get_text(strip=True).lower()
        if not _is_semi_equipment_article_title(title):
            continue
        href = a_tag.get("href")
        if isinstance(href, str):
            links.append(urllib.parse.urljoin(base_url, href))
    return links


def _is_semi_equipment_article_title(title: str) -> bool:
    excluded = (
        "forecast",
        "projected",
        "projection",
        "on track",
        "expected to",
    )
    if any(term in title for term in excluded):
        return False
    return any(
        kw in title
        for kw in (
            "equipment billings",
            "wwsems",
            "semiconductor equipment market",
            "semiconductor equipment sales",
        )
    )


def _parse_semi_annual_article_text(
    text: str,
    *,
    source_url: str,
    default_date: date | None,
) -> dict[str, Any] | None:
    if re.search(
        r"\b(forecast|projected|projection|on track|expected to|will reach)\b",
        text[:1000],
        re.IGNORECASE,
    ):
        return None

    year = _extract_annual_report_year(text)
    if year is None:
        return None

    segment_match = re.search(
        r"global\s+semiconductor\s+equipment\s+(?:sales|billings)[\s\S]{0,500}",
        text,
        re.IGNORECASE,
    )
    segment = segment_match.group(0) if segment_match else text[:800]
    amount_match = re.search(r"((?:US)?\$[\d\.]+\s*billion)", segment, re.IGNORECASE)
    if not amount_match:
        return None

    amount_raw = amount_match.group(1).strip()
    return {
        "report_quarter": f"{year}-ANNUAL",
        "trade_date": date(year, 12, 31),
        "source_record_type": "annual_source",
        "report_year": str(year),
        "global_billings_billion_usd": None,
        "china_billings_billion_usd": None,
        "global_billings_raw": None,
        "china_billings_raw": None,
        "annual_billings_raw": amount_raw,
        "annual_billings_billion_usd": _parse_billion_amount(amount_raw),
        "yoy_growth_raw": _extract_growth_raw(text, "year-over-year"),
        "qoq_growth_raw": None,
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
        "data_status": "annual_source",
    }


def _extract_annual_report_year(text: str) -> int | None:
    patterns = (
        r"\b(20\d{2})\s+global\s+semiconductor\s+equipment\s+(?:sales|billings)\b",
        r"\bglobal\s+semiconductor\s+equipment\s+(?:sales|billings)"
        r"[\s\S]{0,160}?\bin\s+(20\d{2})\b",
        r"\bglobal\s+semiconductor\s+equipment\s+(?:sales|billings)"
        r"[\s\S]{0,160}?\bin\s+calendar\s+year\s+(20\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _parse_english_release_date(text: str) -> date | None:
    metadata_patterns = (
        r"<meta[^>]+property=[\"']article:published_time[\"'][^>]+content=[\"']([^\"']+)",
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']article:published_time[\"']",
        r"[\"']datePublished[\"']\s*:\s*[\"']([^\"']+)",
    )
    for pattern in metadata_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_iso_date(match.group(1))
            if parsed is not None:
                return parsed

    date_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        text,
    )
    if not date_match:
        return None
    month_str, day_str, yr_str = date_match.groups()
    try:
        return date(int(yr_str), _MONTH_NAMES.index(month_str) + 1, int(day_str))
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date | None:
    match = re.match(r"(20\d\d-\d\d-\d\d)", value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _extract_source_url(text: str) -> str | None:
    soup = BeautifulSoup(text, "html.parser")
    for link_tag in soup.find_all("link", href=True):
        if not isinstance(link_tag, Tag):
            continue
        rel_value = link_tag.get("rel")
        rel_values = [rel_value] if isinstance(rel_value, str) else rel_value or []
        if any(str(value).lower() == "canonical" for value in rel_values):
            href = link_tag.get("href")
            if isinstance(href, str) and href.strip():
                return href.strip()

    for selector in ('meta[property="og:url"]', 'meta[name="twitter:url"]'):
        meta_tag = soup.select_one(selector)
        if not isinstance(meta_tag, Tag):
            continue
        content = meta_tag.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _parse_billion_amount(raw_value: str) -> float:
    numeric = re.sub(r"[^\d.-]", "", raw_value)
    return float(numeric)


def _extract_growth_raw(text: str, marker: str) -> str | None:
    patterns: tuple[str, ...]
    if marker == "year-over-year":
        patterns = (
            r"([+\-]?\d+(?:\.\d+)?)\s*%\s+year-over-year",
            r"([+\-]?\d+(?:\.\d+)?)\s*percent\s+year-over-year",
            r"year-over-year[\s\S]{0,40}?([+\-]?\d+(?:\.\d+)?)\s*%",
            r"year-over-year[\s\S]{0,40}?([+\-]?\d+(?:\.\d+)?)\s*percent",
            r"year-over-year[\s\S]{0,40}?(?:up|increase(?:d)?|grow(?:n|s)?|rose|surge(?:d)?)"
            r"[\s\S]{0,20}?([+\-]?\d+(?:\.\d+)?)\s*percent",
            r"(?:up|increase(?:d)?|grow(?:n|s)?|rose|surge(?:d)?)"
            r"[\s\S]{0,20}?([+\-]?\d+(?:\.\d+)?)\s*percent\s+from\s+\d{4}",
            r"(?:down|drop(?:ped)?|decline(?:d)?|slip(?:ped)?|contract(?:ed)?)"
            r"[\s\S]{0,20}?([+\-]?\d+(?:\.\d+)?)\s*percent\s+from\s+\d{4}",
        )
    else:
        patterns = (
            r"(?:contract(?:ed)?|down|drop(?:ped)?|decline(?:d)?|slip(?:ped)?)"
            r"[\s\S]{0,20}?([+\-]?\d+(?:\.\d+)?)\s*percent"
            r"[\s\S]{0,60}?quarter-over-quarter",
            r"(?:contract(?:ed)?|down|drop(?:ped)?|decline(?:d)?|slip(?:ped)?)"
            r"[\s\S]{0,20}?([+\-]?\d+(?:\.\d+)?)\s*%"
            r"[\s\S]{0,60}?quarter-over-quarter",
            r"([+\-]?\d+(?:\.\d+)?)\s*%\s+quarter-over-quarter",
            r"([+\-]?\d+(?:\.\d+)?)\s*percent\s+quarter-over-quarter",
            r"quarter-over-quarter[\s\S]{0,80}?([+\-]?\d+(?:\.\d+)?)\s*%",
            r"quarter-over-quarter[\s\S]{0,80}?([+\-]?\d+(?:\.\d+)?)\s*percent",
            r"([+\-]?\d+(?:\.\d+)?)\s*%\s+(?:growth\s+)?(?:from\s+the\s+)?prior\s+quarter",
            r"([+\-]?\d+(?:\.\d+)?)\s*percent\s+(?:growth\s+)?(?:from\s+the\s+)?prior\s+quarter",
            r"year-over-year\s+and\s+([+\-]?\d+(?:\.\d+)?)\s*%,\s+to",
            r"year-over-year\s+and\s+([+\-]?\d+(?:\.\d+)?)\s*percent,\s+to",
            r"(?:from|over)\s+the\s+(?:prior|previous)\s+quarter[\s\S]{0,40}?"
            r"([+\-]?\d+(?:\.\d+)?)\s*percent",
        )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1)
            context = text[max(match.start() - 20, 0) : match.end()].lower()
            if re.search(
                r"(down|drop(?:ped)?|decline(?:d)?|slip(?:ped)?|contract(?:ed)?)",
                context,
            ):
                value = f"-{value.lstrip('+-')}"
            return f"{value}%"
    return None
