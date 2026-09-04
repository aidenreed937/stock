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
    """从 SEMI/PR Newswire 新闻通报文本解析设备出货额与报告季度。

    季度声明必须与金额在同一上下文窗口（季度词前后各 400/800 字符）内绑定：
    页面侧栏"相关新闻"链接标题也含 "Qx YYYY" 字样，但不带金额，若直接全文
    匹配会把年度公报误判为季度公报（实测 2025 年度 135B 公报被误判为 2026-Q2）。
    """
    if not text:
        return None

    # 遍历所有季度声明，收集「同句内带金额」的候选，取金额与季度词距离最近的
    candidates: list[dict[str, Any]] = []
    for q_match in re.finditer(
        r"(first[-\s]+quarter|second[-\s]+quarter|third[-\s]+quarter|fourth[-\s]+quarter|q[1-4])"
        r"\s+(?:of\s+)?(\d{4})",
        text,
        re.IGNORECASE,
    ):
        q_name, year_str = q_match.groups()
        q_num = QUARTER_WORDS_MAP.get(q_name.lower().replace("-", " "))
        if not q_num:
            continue
        sent_start, sent_end = _sentence_bounds(text, q_match.start(), q_match.end())
        billings_match = _search_billings_in_window(text, sent_start, sent_end)
        if billings_match is None:
            continue  # 侧栏/导航中的季度词同句无金额，跳过
        candidates.append(
            {
                "q_num": q_num,
                "year": int(year_str),
                "billings_match": billings_match,
                "distance": abs(billings_match.start() - (q_match.start() + q_match.end()) // 2),
                # china 金额常在同一句或紧邻下一句，扩展窗口至句尾后 600 字符
                "win_start": sent_start,
                "win_end": min(len(text), sent_end + 600),
            }
        )
    if not candidates:
        return _parse_semi_annual_article_text(
            text,
            source_url=source_url,
            default_date=default_date,
        )
    best = min(candidates, key=lambda item: item["distance"])

    china_match = re.search(
        r"China[^\.\n]*?(?:spending|investments|sales|billings)?[^\.\n]*?"
        r"(\$[\d\.]+\s*billion)",
        text[best["win_start"] : best["win_end"]],
        re.IGNORECASE,
    )

    month_end = best["q_num"] * 3
    day_end = 31 if month_end in (3, 12) else 30
    trade_date = date(best["year"], month_end, day_end)

    return {
        "report_quarter": f"{best['year']}-Q{best['q_num']}",
        "trade_date": trade_date,
        "source_record_type": "quarterly_actual",
        "report_year": str(best["year"]),
        "global_billings_billion_usd": _parse_billion_amount(best["billings_match"].group(1)),
        "china_billings_billion_usd": (
            _parse_billion_amount(china_match.group(1)) if china_match else None
        ),
        "global_billings_raw": best["billings_match"].group(1).strip(),
        "china_billings_raw": china_match.group(1).strip() if china_match else None,
        "annual_billings_raw": None,
        "yoy_growth_raw": _extract_growth_raw(text, "year-over-year"),
        "qoq_growth_raw": _extract_growth_raw(text, "quarter-over-quarter"),
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
    }


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\"'(])")


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """返回包含 [start, end) 的句子边界。

    标点后跟大写/引号视为分句，避免小数点在金额内误分；换行不视为分句，兼容
    多行纯文本样本。
    """
    sent_start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        if m.end() <= start:
            sent_start = m.end()
        elif m.start() >= end:
            return sent_start, m.start()
    return sent_start, len(text)


def _search_billings_in_window(text: str, start: int, end: int) -> re.Match[str] | None:
    """在窗口内搜索出货额：优先"动词 + 金额"，回退"金额 + 季度词"。"""
    billings_match = re.search(
        r"(?:increased|reached|reach|registered|sales of|billings of|to)\s+"
        r"(?:a\s+record\s+|record\s+)?"
        r"((?:US)?\$[\d\.]+\s*billion)",
        text[start:end],
        re.IGNORECASE,
    )
    if billings_match:
        return billings_match
    return re.search(
        r"(\$[\d\.]+\s*billion)\s+(?:in\s+the\s+)?"
        r"(?:first|second|third|fourth|q[1-4])",
        text[start:end],
        re.IGNORECASE,
    )


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

    annual = _extract_annual_claim(text)
    if annual is None:
        return None
    year, amount_raw = annual
    china_amount_raw = _extract_annual_china_amount(text, year)

    return {
        "report_quarter": f"{year}-ANNUAL",
        "trade_date": date(year, 12, 31),
        "source_record_type": "annual_source",
        "report_year": str(year),
        "global_billings_billion_usd": None,
        "china_billings_billion_usd": (
            _parse_billion_amount(china_amount_raw) if china_amount_raw else None
        ),
        "global_billings_raw": None,
        "china_billings_raw": china_amount_raw,
        "annual_billings_raw": amount_raw,
        "annual_billings_billion_usd": _parse_billion_amount(amount_raw),
        "yoy_growth_raw": _extract_growth_raw(text, "year-over-year"),
        "qoq_growth_raw": None,
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
        "data_status": "annual_source",
    }


def _extract_annual_claim(text: str) -> tuple[int, str] | None:
    """年度公报：在「含金额」的句子内提取报告年份与年度总额。

    同样要求句子级绑定（年度词与金额同句），避免页面侧栏"相关新闻"链接标题
    （如 "…in Q2 2026"）污染年份提取。
    """
    year_patterns = (
        r"\b(20\d{2})\s+(?:global|worldwide)\s+"
        r"(?:semiconductor(?:\s+manufacturing)?\s+equipment\s+(?:sales|billings)|"
        r"sales\s+of\s+semiconductor(?:\s+manufacturing)?\s+equipment)\b",
        r"\b(?:global|worldwide)\s+semiconductor(?:\s+manufacturing)?\s+equipment\s+"
        r"(?:sales|billings)[\s\S]{0,160}?\b(?:in|during|for)\s+(20\d{2})\b",
        r"\b(?:global|worldwide)\s+sales\s+of\s+semiconductor"
        r"(?:\s+manufacturing)?\s+equipment[\s\S]{0,160}?"
        r"\b(?:in|during|for)\s+(20\d{2})\b",
        r"\b(?:global|worldwide)\s+semiconductor(?:\s+manufacturing)?\s+equipment\s+"
        r"(?:sales|billings)[\s\S]{0,160}?\bin\s+calendar\s+year\s+(20\d{2})\b",
    )
    prev_end = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        sent = text[prev_end : m.start()]
        prev_end = m.end()
        claim = _annual_claim_in_sentence(sent, year_patterns)
        if claim is not None:
            return claim
    claim = _annual_claim_in_sentence(text[prev_end:], year_patterns)
    return claim


def _annual_claim_in_sentence(
    sent: str,
    year_patterns: tuple[str, ...],
) -> tuple[int, str] | None:
    if not re.search(
        r"\b(?:global|worldwide)\s+semiconductor(?:\s+manufacturing)?\s+equipment\s+"
        r"(?:sales|billings)\b|"
        r"\b(?:global|worldwide)\s+sales\s+of\s+semiconductor"
        r"(?:\s+manufacturing)?\s+equipment\b",
        sent,
        re.IGNORECASE,
    ):
        return None
    amount = re.search(r"((?:US)?\$[\d\.]+\s*billion)", sent, re.IGNORECASE)
    if not amount:
        return None
    year: int | None = None
    for pattern in year_patterns:
        ymatch = re.search(pattern, sent, re.IGNORECASE)
        if ymatch:
            year = int(ymatch.group(1))
            break
    if year is None:
        return None
    return year, amount.group(1).strip()


def _extract_annual_china_amount(text: str, year: int) -> str | None:
    """提取年度公报中的 China 区域总额，保留源端金额字符串。"""
    soup = BeautifulSoup(text, "html.parser")
    for node in soup.find_all(["script", "style", "noscript"]):
        node.decompose()
    plain_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = (
        r"\b(?:sales|spending|investments?|billings)\b[^.!?]{0,120}?\bChina\b"
        r"[^.!?]{0,180}?((?:US)?\$[\d,.]+\s*billion)",
        r"\bChina\b[^.!?]{0,240}?\b(?:sales|spending|investments?|billings|market)\b"
        r"[^.!?]{0,140}?((?:US)?\$[\d,.]+\s*billion)",
    )
    for pattern in patterns:
        match = re.search(pattern, plain_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    for table in soup.find_all("table"):
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
        ]
        rows = [row for row in rows if row]
        table_text = " ".join(cell for row in rows for cell in row)
        if str(year) not in table_text:
            continue

        target_index: int | None = None
        for row in rows:
            for index, cell in enumerate(row):
                if cell.strip() == str(year):
                    target_index = index
                    break
            if target_index is not None:
                break

        for row in rows:
            if not row or row[0].strip().casefold() != "china":
                continue
            candidates = (
                [row[target_index]]
                if target_index is not None and target_index < len(row)
                else row[1:]
            )
            for candidate in candidates:
                if re.fullmatch(r"(?:US)?\$?[\d,]+(?:\.\d+)?(?:\s+billion)?", candidate):
                    return str(candidate).strip()
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
