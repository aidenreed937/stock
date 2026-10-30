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

# 区域表的规范区域名映射（同一区域在不同期公报里写法不一）。
_REGION_ALIASES = {
    "china": "China",
    "korea": "Korea",
    "south korea": "Korea",
    "taiwan": "Taiwan",
    "japan": "Japan",
    "europe": "Europe",
    "north america": "North America",
    "rest of the world": "Rest of World",
    "rest of world": "Rest of World",
    "row": "Rest of World",
}

# 区域表只出现在部分期次的文本表格里；该短语用于快速筛掉无关页面。
_REGIONAL_TABLE_GATE = re.compile(r"by\s+region", re.IGNORECASE)

# 表头季度标签的三种写法：Q12020 / 1Q2018 / 1Q18。
_QUARTER_LABEL_PATTERNS = (
    re.compile(r"q([1-4])(20\d{2})", re.IGNORECASE),
    re.compile(r"([1-4])q(20\d{2})", re.IGNORECASE),
    re.compile(r"([1-4])q(\d{2})", re.IGNORECASE),
)


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
    if not _is_equipment_release_page(text):
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
    return _build_quarterly_record(
        text,
        min(candidates, key=lambda item: item["distance"]),
        source_url=source_url,
        default_date=default_date,
    )


def _is_equipment_release_page(text: str) -> bool:
    """排除首页/列表页中相邻新闻卡片拼接出的季度与金额。"""
    title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", text, re.IGNORECASE | re.DOTALL)
    if title_match is None:
        return True
    title = BeautifulSoup(title_match.group(1), "html.parser").get_text(" ", strip=True)
    return bool(
        re.search(
            r"\b(?:global|worldwide)\b[\s\S]{0,120}\bsemiconductor\b"
            r"[\s\S]{0,120}\bequipment\b[\s\S]{0,120}\b(?:billings|sales)\b",
            title,
            re.IGNORECASE,
        )
    )


def _build_quarterly_record(
    text: str,
    best: dict[str, Any],
    *,
    source_url: str,
    default_date: date | None,
) -> dict[str, Any]:
    """由选定的季度候选组装季度记录。

    China 出货额优先取**区域表**（当季列），只有表格不存在时才回退到正文里
    ``China … $X billion`` 的措辞。原因见 :func:`_extract_regional_billings`。
    """
    report_quarter = f"{best['year']}-Q{best['q_num']}"
    china_match = re.search(
        r"China[^\.\n]*?(?:spending|investments|sales|billings)?[^\.\n]*?"
        r"(\$[\d\.]+\s*billion)",
        text[best["win_start"] : best["win_end"]],
        re.IGNORECASE,
    )
    regional_billings, regional_header_raw = _extract_regional_billings(text, report_quarter)
    china = (regional_billings or {}).get("China")
    month_end = best["q_num"] * 3
    day_end = 31 if month_end in (3, 12) else 30

    return {
        "report_quarter": report_quarter,
        "trade_date": date(best["year"], month_end, day_end),
        "source_record_type": "quarterly_actual",
        "report_year": str(best["year"]),
        "global_billings_billion_usd": _parse_billion_amount(best["billings_match"].group(1)),
        "global_billings_raw": best["billings_match"].group(1).strip(),
        "china_billings_billion_usd": (
            china["billings_billion_usd"]
            if china is not None
            else (_parse_billion_amount(china_match.group(1)) if china_match else None)
        ),
        "china_billings_raw": (
            china["billings_raw"]
            if china is not None
            else (china_match.group(1).strip() if china_match else None)
        ),
        "annual_billings_raw": None,
        # 增速只在「季度金额所在窗口」内提取，避免页脚/侧栏"相关新闻"链接标题的
        # 年度或他期增速（如 "23% Year-Over-Year in Q2 2026"）污染当前季度值。
        "yoy_growth_raw": _extract_growth_raw(
            text[best["win_start"] : best["win_end"]], "year-over-year"
        ),
        "qoq_growth_raw": _extract_growth_raw(
            text[best["win_start"] : best["win_end"]], "quarter-over-quarter"
        ),
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
        "regional_billings": regional_billings,
        "regional_billings_header_raw": regional_header_raw,
    }


def _extract_regional_billings(
    html_text: str,
    report_quarter: str,
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """解析新闻稿里的「分区域季度出货额」文本表格。

    只有早期公报把区域表以**文本表格**发布（2018-Q1~2020-Q1 共 7 期）；2021 年起
    SEMI 改为**内嵌图片**（``alt="Semiconductor Equipment Billings by region"``），
    表格在 HTML 里并不存在，此时返回 ``(None, None)``。

    提取前校验表头首列季度与本次解析出的报告期一致，避免把"相关新闻"里的他期
    表格当成当季。只取当季列与两个披露增速；上季/去年同期列可从相邻季度行的
    当季列取得，原始快照仍是完整血统。

    返回 ``(区域名 -> 取值映射, 表头原文)``。
    """
    if not html_text or _REGIONAL_TABLE_GATE.search(html_text) is None:
        return None, None
    soup = BeautifulSoup(html_text, "html.parser")
    for table in soup.find_all("table"):
        parsed = _parse_region_table(table, report_quarter)
        if parsed is not None:
            return parsed
    return None, None


def _parse_region_table(
    table: Tag,
    report_quarter: str,
) -> tuple[dict[str, dict[str, Any]], str] | None:
    """把单个 ``<table>`` 解析为区域取值映射；不像区域表则返回 ``None``。"""
    rows = table.find_all("tr")
    if len(rows) < 3:
        return None
    header_cells = _row_cells(rows[0])
    labelled = next(
        (q for q in (_quarter_from_column_label(cell) for cell in header_cells[:3]) if q),
        None,
    )
    if labelled is not None and labelled != report_quarter:
        return None

    regions: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        cells = _row_cells(row)
        region = _normalise_region_label(cells[0]) if cells else None
        if region is None or len(cells) < 2:
            continue
        billings = _to_float(cells[1])
        if billings is None:
            continue
        regions[region] = {
            "billings_raw": cells[1],
            "billings_billion_usd": billings,
            "qoq_raw": cells[4] if len(cells) > 4 else None,
            "yoy_raw": cells[5] if len(cells) > 5 else None,
        }
    if len(regions) < 4:
        return None
    return regions, " | ".join(header_cells)


def _row_cells(row: Tag) -> list[str]:
    """取一行里的非空单元格文本。"""
    cells: list[str] = []
    for cell in row.find_all(["td", "th"]):
        text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
        if text:
            cells.append(text)
    return cells


def _normalise_region_label(value: str) -> str | None:
    """把区域标签规范化为统一名称，非区域行（如 ``Total``）返回 ``None``。"""
    return _REGION_ALIASES.get(re.sub(r"\s+", " ", value or "").strip().lower())


def _quarter_from_column_label(value: str) -> str | None:
    """把表头季度标签（Q12020 / 1Q2018 / 1Q18）规范化为 ``2018-Q1`` 形式。"""
    label = re.sub(r"\s+", "", value or "")
    for index, pattern in enumerate(_QUARTER_LABEL_PATTERNS):
        match = pattern.fullmatch(label)
        if match is None:
            continue
        quarter, year = match.group(1), match.group(2)
        if index == 2:
            year = f"20{year}"
        return f"{year}-Q{quarter}"
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


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
    year, amount_raw, claim_start, claim_end = annual
    table_total = _extract_annual_total_from_table(text, year)
    if table_total:
        amount_raw = table_total
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
        # 增速只在「年度声明本句」内提取：页脚/侧栏"相关新闻"标题的增速
        # （实测 "23% Year-Over-Year in Q2 2026"）会污染年度值，宁可留空。
        "yoy_growth_raw": _extract_growth_raw(text[claim_start:claim_end], "year-over-year"),
        "qoq_growth_raw": None,
        "release_date": _parse_english_release_date(text) or default_date,
        "source_url": source_url or _extract_source_url(text) or "",
        "data_status": "annual_source",
    }


def _extract_annual_claim(text: str) -> tuple[int, str, int, int] | None:
    """年度公报：在「含金额」的句子内提取报告年份、年度总额与该句在原文中的窗口。

    返回 ``(year, amount_raw, sentence_start, sentence_end)``。

    同样要求句子级绑定（年度词与金额同句），避免页面侧栏"相关新闻"链接标题
    （如 "…in Q2 2026"）污染年份提取。额外返回句子边界，是为了让增速提取也
    落在**年度声明本句**内——否则页脚/侧栏的 "23% Year-Over-Year in Q2 2026"
    会被写成该年度的同比。
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
        sent_start, sent_end = prev_end, m.start()
        prev_end = m.end()
        claim = _annual_claim_in_sentence(text[sent_start:sent_end], year_patterns)
        if claim is not None:
            return (*claim, sent_start, sent_end)
    claim = _annual_claim_in_sentence(text[prev_end:], year_patterns)
    if claim is None:
        return None
    return (*claim, prev_end, len(text))


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


def _extract_annual_total_from_table(text: str, year: int) -> str | None:
    """提取年度公报表格中的 Total / Worldwide 汇总金额（保持两位小数精度）。"""
    soup = BeautifulSoup(text, "html.parser")
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
            if not row or row[0].strip().casefold() not in ("total", "worldwide"):
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
