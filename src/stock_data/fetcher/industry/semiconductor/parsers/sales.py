"""SIA / WSTS 半导体销售额 RAW 解析器。"""

import calendar
import gzip
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorSalesRecord

MONTH_MAP = {
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
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_GROWTH_MARKER_PATTERNS = {
    "year-to-year": re.compile(
        r"\b(?:year-to-year|year-over-year|year-on-year|year\s+over\s+year|year\s+on\s+year)\b",
        re.IGNORECASE,
    ),
    "month-to-month": re.compile(
        r"\b(?:month-to-month|month-on-month|month\s+over\s+month)\b",
        re.IGNORECASE,
    ),
}
_YEAR_COMPARISON_PATTERN = re.compile(
    r"\bcompared\s+(?:to|with)\s+(?:the\s+)?(?:same\s+month\s+)?last\s+year\b"
    r"|\bcompared\s+(?:to|with)\s+(?:the\s+)?[A-Za-z]+\s+20\d\d\b",
    re.IGNORECASE,
)
_MONTH_COMPARISON_PATTERN = re.compile(
    r"\bcompared\s+(?:to|with)\s+(?:the\s+)?(?:last|previous|prior)\s+month\b"
    r"|\bcompared\s+(?:to|with)\s+(?:the\s+)?[A-Za-z]+\s+20\d\d\b",
    re.IGNORECASE,
)
_PERCENT_TOKEN = re.compile(
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<unit>%|percent)",
    re.IGNORECASE,
)
_DIRECTION_TOKEN = re.compile(
    r"\b(?P<negative>down|decreased|decrease|declined|decline|fell|fall|lower|slipped|slip)\b"
    r"|\b(?P<positive>up|increased|increase|grew|grow|rose|rise|higher|gained|gain)\b"
    r"|\b(?P<flat>flat|steady)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _WstsParsedItem:
    report_month: str
    trade_date: date
    global_sales_usd: float
    americas_sales_usd: float | None
    europe_sales_usd: float | None
    japan_sales_usd: float | None
    asia_pacific_sales_usd: float | None
    worldwide_raw: str | None
    americas_raw: str | None
    europe_raw: str | None
    japan_raw: str | None
    asia_pacific_raw: str | None


def parse_wsts_excel_file(
    excel_path: Path,
    release_dates: Mapping[str, date] | None = None,
) -> list[SemiconductorSalesRecord]:
    """解析 WSTS 官方 Historical Billings Excel 文件的 3MMA 工作表。"""
    df_raw = pd.read_excel(pd.ExcelFile(excel_path), sheet_name="3MMA")
    raw_list = _parse_wsts_raw_rows(df_raw)
    raw_list.sort(key=lambda x: x.trade_date)
    return _build_sales_records(raw_list, release_dates=release_dates)


def parse_sia_china_and_date(html_text: str, source_url: str) -> dict[str, Any] | None:
    """从 SIA 新闻 HTML 中抽取月份、发布日期及中国区销售与增速数据。"""
    report_month = _extract_report_month(html_text)
    if report_month is None:
        return None

    yoy_detail = _extract_china_growth_detail(
        html_text,
        "year-to-year",
        report_month=report_month,
    )
    mom_detail = _extract_china_growth_detail(
        html_text,
        "month-to-month",
        report_month=report_month,
    )

    return {
        "report_month": report_month,
        "release_date": _extract_release_date(html_text),
        "china_sales_usd": _extract_china_sales(html_text),
        "china_yoy_growth": yoy_detail[1] if yoy_detail is not None else None,
        "china_mom_growth": mom_detail[1] if mom_detail is not None else None,
        "china_sales_raw": _extract_china_sales_raw(html_text),
        "china_yoy_growth_raw": yoy_detail[0] if yoy_detail is not None else None,
        "china_mom_growth_raw": mom_detail[0] if mom_detail is not None else None,
        "source_url": source_url,
    }


def extract_sia_sales_article_links(html_text: str) -> list[str]:
    """从 SIA 最新新闻列表页解析全球半导体销售月报链接。"""
    return list(
        dict.fromkeys(
            re.findall(
                r'href="(https://www\.semiconductors\.org/global-semiconductor-sales-[^"]+)"',
                html_text,
            )
        )
    )


def load_sia_news_enrichments(raw_dir: Path | str) -> dict[str, dict[str, Any]]:
    """从已归档 SIA HTML 新闻中读取报告月与真实发布日期。"""
    enrichments: dict[str, dict[str, Any]] = {}
    root = Path(raw_dir)
    if not root.exists():
        return enrichments

    for path in sorted(root.glob("*.html.gz")):
        if path.name == "latest_news_list.html.gz":
            continue
        try:
            with gzip.open(path, "rb") as fh:
                content_bytes = fh.read()
            text = content_bytes.decode("utf-8", errors="ignore")
        except OSError:
            continue
        parsed = parse_sia_china_and_date(text, str(path))
        if parsed is None or parsed.get("release_date") is None:
            continue
        parsed["raw_content_sha256"] = raw_content_sha256(content_bytes)
        parsed["raw_snapshot_path"] = raw_snapshot_path_value(path, root.parent)
        report_month = str(parsed["report_month"])
        existing = enrichments.get(report_month)
        if existing is None or str(parsed["release_date"]) >= str(existing["release_date"]):
            enrichments[report_month] = parsed
    return enrichments


def _parse_wsts_raw_rows(df_raw: pd.DataFrame) -> list[_WstsParsedItem]:
    raw_list: list[_WstsParsedItem] = []
    i = 3
    while i < len(df_raw):
        year = _parse_year_cell(df_raw.iloc[i, 0])
        if year is None:
            i += 1
            continue
        raw_list.extend(_parse_wsts_year_block(df_raw, i, year))
        i += 6
    return raw_list


def _parse_wsts_year_block(
    df_raw: pd.DataFrame,
    row_index: int,
    year: int,
) -> list[_WstsParsedItem]:
    regions: dict[str, list[Any]] = {}
    for offset in range(1, 6):
        if row_index + offset < len(df_raw):
            reg_name = str(df_raw.iloc[row_index + offset, 0]).strip()
            regions[reg_name.lower()] = list(df_raw.iloc[row_index + offset, 1:13].values)

    worldwide_vals = regions.get("worldwide", [])
    americas_vals = regions.get("americas", [])
    europe_vals = regions.get("europe", [])
    japan_vals = regions.get("japan", [])
    asia_vals = regions.get("asia pacific", [])

    items: list[_WstsParsedItem] = []
    for m_idx, worldwide_val in enumerate(worldwide_vals[:12]):
        if not _is_positive_number(worldwide_val):
            continue
        month = m_idx + 1
        items.append(
            _WstsParsedItem(
                report_month=f"{year:04d}-{month:02d}",
                trade_date=date(year, month, calendar.monthrange(year, month)[1]),
                global_sales_usd=round(float(worldwide_val) / 1_000_000.0, 3),
                americas_sales_usd=_region_billings(americas_vals, m_idx),
                europe_sales_usd=_region_billings(europe_vals, m_idx),
                japan_sales_usd=_region_billings(japan_vals, m_idx),
                asia_pacific_sales_usd=_region_billings(asia_vals, m_idx),
                worldwide_raw=_source_cell_string(worldwide_val),
                americas_raw=_region_raw_value(americas_vals, m_idx),
                europe_raw=_region_raw_value(europe_vals, m_idx),
                japan_raw=_region_raw_value(japan_vals, m_idx),
                asia_pacific_raw=_region_raw_value(asia_vals, m_idx),
            )
        )
    return items


def _build_sales_records(
    raw_list: list[_WstsParsedItem],
    release_dates: Mapping[str, date] | None = None,
) -> list[SemiconductorSalesRecord]:
    records: list[SemiconductorSalesRecord] = []
    for item in raw_list:
        records.append(
            SemiconductorSalesRecord(
                report_month=item.report_month,
                trade_date=item.trade_date,
                global_sales_usd=item.global_sales_usd,
                americas_sales_usd=item.americas_sales_usd,
                europe_sales_usd=item.europe_sales_usd,
                japan_sales_usd=item.japan_sales_usd,
                asia_pacific_sales_usd=item.asia_pacific_sales_usd,
                # YoY/MoM 是 Curated 层基于 RAW 数值计算的派生字段。
                yoy_growth=None,
                mom_growth=None,
                unit="billion_usd",
                source="WSTS/SIA",
                source_url="https://www.wsts.org/67/Historical-Billings-Report",
                release_date=(release_dates or {}).get(item.report_month),
                data_status="actual",
                collected_at=now_utc_iso(),
                worldwide_raw=item.worldwide_raw,
                americas_raw=item.americas_raw,
                europe_raw=item.europe_raw,
                japan_raw=item.japan_raw,
                asia_pacific_raw=item.asia_pacific_raw,
            )
        )
    return records


def _parse_year_cell(value: object) -> int | None:
    if pd.isna(value):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _is_positive_number(value: object) -> bool:
    return pd.notna(value) and isinstance(value, int | float) and value > 0


def _region_billings(values: list[Any], index: int) -> float | None:
    if index >= len(values) or pd.isna(values[index]):
        return None
    return round(float(values[index]) / 1_000_000.0, 3)


def _region_raw_value(values: list[Any], index: int) -> str | None:
    if index >= len(values) or pd.isna(values[index]):
        return None
    return _source_cell_string(values[index])


def _source_cell_string(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _extract_release_date(html_text: str) -> date | None:
    metadata_patterns = (
        r"<meta[^>]+property=[\"']article:published_time[\"'][^>]+content=[\"']([^\"']+)",
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']article:published_time[\"']",
        r"[\"']datePublished[\"']\s*:\s*[\"']([^\"']+)",
    )
    for pattern in metadata_patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        parsed = _parse_iso_date_prefix(match.group(1)) if match else None
        if parsed is not None:
            return parsed

    visible_patterns = (
        r"\b(?:WASHINGTON|SAN\s+JOSE(?:,\s*Calif\.)?)[—–,\-\s]+"
        r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(20\d\d)",
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(20\d\d)",
        r"\b([A-Za-z]+)\.?\s+(\d{1,2}),\s*(20\d\d)\b",
    )
    for pattern in visible_patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if not match:
            continue
        month_str, day_str, year_str = match.groups()
        month_num = MONTH_MAP.get(month_str.lower().rstrip("."))
        if not month_num:
            continue
        try:
            return date(int(year_str), month_num, int(day_str))
        except ValueError:
            continue
    return None


def _parse_iso_date_prefix(value: str) -> date | None:
    match = re.match(r"(20\d\d-\d\d-\d\d)", value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _extract_report_month(html_text: str) -> str | None:
    visible_text = _visible_html_text(html_text)
    patterns = (
        r"\b(?:sales|billings)\b[^!?]{0,180}?\b(?:for|during)\s+the\s+month\s+of\s+"
        r"([A-Za-z]+)\.?\s+(20\d\d)\b",
        r"\b(?:sales|billings)\b[^!?]{0,180}?\b(?:for|during)\s+the\s+month\s+"
        r"([A-Za-z]+)\.?\s+(20\d\d)\b",
        r"\b(?:sales|billings)\s+(?:for|during)\s+the\s+month\s+of\s+"
        r"([A-Za-z]+)\.?\s+(20\d\d)\b",
        r"\b(?:sales|billings)\s+for\s+the\s+month\s+"
        r"([A-Za-z]+)\.?\s+(20\d\d)\b",
        r"\b(?:sales|billings)\s+(?:in|during)\s+"
        r"([A-Za-z]+)\.?\s+(20\d\d)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, visible_text, re.IGNORECASE)
        if match is None:
            continue
        month_str, year_str = match.groups()
        month_num = MONTH_MAP.get(month_str.lower().rstrip("."))
        if month_num:
            return f"{int(year_str):04d}-{month_num:02d}"
    return None


def _extract_china_growth(html_text: str, marker: str) -> float | None:
    """抽取带有局部区域语义的 China 增速。"""
    detail = _extract_china_growth_detail(html_text, marker)
    return detail[1] if detail is not None else None


def _extract_china_growth_raw(html_text: str, marker: str) -> str | None:
    """抽取 China 增速的源端数值文本，不带解析后的方向推断。"""
    detail = _extract_china_growth_detail(html_text, marker)
    return detail[0] if detail is not None else None


def _extract_fallback_china_yoy(html_text: str) -> float | None:
    """兼容旧调用方，使用与主解析相同的局部语义规则。"""
    detail = _extract_china_growth_detail(html_text, "year-to-year")
    return detail[1] if detail is not None else None


def _extract_china_growth_detail(
    html_text: str,
    marker: str,
    *,
    report_month: str | None = None,
) -> tuple[str, float] | None:
    """返回 (源端数值文本, 带方向的增速小数)。"""
    marker_pattern = _marker_pattern(marker)
    visible_text = _visible_html_text(html_text)
    sentences = _split_growth_sentences(_extract_regionally_text(visible_text))
    candidates = [
        sentence
        for sentence in sentences
        if re.search(r"\bChina\b", sentence, re.IGNORECASE)
        and _sentence_matches_marker(
            sentence,
            marker,
            marker_pattern,
            report_month=report_month,
        )
    ]

    for sentence in candidates:
        detail = _extract_china_growth_from_sentence(
            sentence,
            marker=marker,
            marker_pattern=marker_pattern,
            report_month=report_month,
        )
        if detail is not None:
            return detail
    return None


def _marker_pattern(marker: str) -> re.Pattern[str]:
    return _GROWTH_MARKER_PATTERNS.get(
        marker,
        re.compile(re.escape(marker), re.IGNORECASE),
    )


def _extract_regionally_text(visible_text: str) -> str:
    match = re.search(r"\b(?:Regionally,|On a regional basis,)", visible_text, re.IGNORECASE)
    if match is None:
        return visible_text
    regionally_text = visible_text[match.start() :]
    boundary = re.search(
        r"\b(?:For comprehensive|Additionally,|About SIA|Media Contact)\b",
        regionally_text,
        re.IGNORECASE,
    )
    return regionally_text[: boundary.start()] if boundary else regionally_text


def _split_growth_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])[\"'”’]?\s+", text)
        if sentence.strip()
    ]


def _sentence_matches_marker(
    sentence: str,
    marker: str,
    marker_pattern: re.Pattern[str],
    *,
    report_month: str | None,
) -> bool:
    if marker_pattern.search(sentence):
        return True
    if report_month is not None:
        if marker == "year-to-year" and _YEAR_COMPARISON_PATTERN.search(sentence):
            return _comparison_matches_period(sentence, report_month, "year")
        if marker == "month-to-month" and _MONTH_COMPARISON_PATTERN.search(sentence):
            return _comparison_matches_period(sentence, report_month, "month")
        return False
    if marker == "year-to-year":
        return bool(
            _YEAR_COMPARISON_PATTERN.search(sentence)
            and not _MONTH_COMPARISON_PATTERN.search(sentence)
        )
    if marker == "month-to-month":
        return bool(_MONTH_COMPARISON_PATTERN.search(sentence))
    return False


def _comparison_matches_period(sentence: str, report_month: str, period: str) -> bool:
    try:
        report_year = int(report_month[:4])
        report_month_number = int(report_month[5:7])
    except (TypeError, ValueError):
        return False

    if period == "year" and re.search(
        r"\bcompared\s+(?:to|with)\s+(?:the\s+)?(?:same\s+month\s+)?last\s+year\b",
        sentence,
        re.IGNORECASE,
    ):
        return True
    if period == "month" and re.search(
        r"\bcompared\s+(?:to|with)\s+(?:the\s+)?(?:last|previous|prior)\s+month\b",
        sentence,
        re.IGNORECASE,
    ):
        return True

    matches = re.finditer(
        r"\bcompared\s+(?:to|with)\s+(?:the\s+)?([A-Za-z]+)\s+(20\d\d)\b",
        sentence,
        re.IGNORECASE,
    )
    previous_month = report_month_number - 1
    previous_year = report_year
    if previous_month == 0:
        previous_month = 12
        previous_year -= 1
    for match in matches:
        target_month = MONTH_MAP.get(match.group(1).lower().rstrip("."))
        if target_month is None:
            continue
        target_year = int(match.group(2))
        if period == "year" and target_month == report_month_number:
            if target_year == report_year - 1:
                return True
        if period == "month" and target_month == previous_month and target_year == previous_year:
            return True
    return False


def _extract_china_growth_from_sentence(
    sentence: str,
    *,
    marker: str,
    marker_pattern: re.Pattern[str],
    report_month: str | None,
) -> tuple[str, float] | None:
    china_matches = list(re.finditer(r"\bChina\b", sentence, re.IGNORECASE))
    for china_match in china_matches:
        tail = sentence[china_match.end() : china_match.end() + 260]
        if not _china_match_matches_marker(
            sentence,
            china_match.start(),
            tail,
            marker=marker,
            marker_pattern=marker_pattern,
            report_month=report_month,
        ):
            continue
        parenthesized = re.match(r"\s*,?\s*\(([^)]*)\)", tail)
        if parenthesized:
            contents = parenthesized.group(1)
            tokens = list(_PERCENT_TOKEN.finditer(contents))
            if not tokens:
                continue

            selected = _select_china_percent_token(
                contents,
                tokens,
                marker=marker,
                sentence=sentence,
            )
            if selected is None:
                continue
            return _build_signed_growth(
                selected,
                context=sentence,
                value_offset=(china_match.end() + parenthesized.start(1) + selected.start()),
            )

        window_start = max(0, china_match.start() - 180)
        window_end = min(len(sentence), china_match.end() + 180)
        window = sentence[window_start:window_end]
        if not _sentence_matches_marker(
            sentence,
            marker,
            marker_pattern,
            report_month=report_month,
        ):
            continue
        tokens = list(_PERCENT_TOKEN.finditer(window))
        if not tokens:
            continue
        selected = min(
            tokens,
            key=lambda token: abs(token.start() - (china_match.start() - window_start)),
        )
        return _build_signed_growth(
            selected,
            context=sentence,
            value_offset=window_start + selected.start(),
        )
    return None


def _china_match_matches_marker(
    sentence: str,
    china_start: int,
    tail: str,
    *,
    marker: str,
    marker_pattern: re.Pattern[str],
    report_month: str | None,
) -> bool:
    if report_month is None:
        return True
    if marker_pattern.search(tail):
        return True

    prefix = sentence[:china_start]
    if marker_pattern.search(prefix):
        return True
    if marker == "year-to-year" and _YEAR_COMPARISON_PATTERN.search(prefix):
        return _comparison_matches_period(prefix, report_month, "year")
    if marker == "month-to-month" and _MONTH_COMPARISON_PATTERN.search(prefix):
        return _comparison_matches_period(prefix, report_month, "month")
    return False


def _select_china_percent_token(
    contents: str,
    tokens: list[re.Match[str]],
    *,
    marker: str,
    sentence: str,
) -> re.Match[str] | None:
    marker_pattern = _marker_pattern(marker)

    marked = [
        token for token in tokens if marker_pattern.search(contents[token.end() : token.end() + 32])
    ]
    if marked:
        return marked[0]
    if len(tokens) == 1:
        return tokens[0]

    marker_positions = []
    for name in ("year-to-year", "month-to-month"):
        pattern = _GROWTH_MARKER_PATTERNS[name]
        match = pattern.search(sentence)
        if match is not None:
            marker_positions.append((match.start(), name))
    marker_positions.sort()
    ordered_markers = [name for _, name in marker_positions]
    try:
        token_index = ordered_markers.index(marker)
    except ValueError:
        return None
    return tokens[token_index] if token_index < len(tokens) else None


def _build_signed_growth(
    token: re.Match[str],
    *,
    context: str,
    value_offset: int,
) -> tuple[str, float]:
    raw_number = token.group("value")
    value = abs(float(raw_number)) / 100.0
    if raw_number.startswith("-"):
        value = -value
    elif not raw_number.startswith("+"):
        direction = _direction_before_value(context, value_offset)
        if direction < 0:
            value = -value
    return f"{raw_number}%", round(value, 4)


def _direction_before_value(context: str, value_offset: int) -> int:
    prefix_start = max(0, value_offset - 160)
    directions = list(_DIRECTION_TOKEN.finditer(context[prefix_start:value_offset]))
    if directions:
        direction = directions[-1]
        if direction.group("negative"):
            return -1
        if direction.group("flat"):
            return 0
        return 1
    following = _DIRECTION_TOKEN.search(context[value_offset : value_offset + 80])
    if following is not None:
        if following.group("negative"):
            return -1
        if following.group("flat"):
            return 0
        return 1
    return 1


def _visible_html_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _extract_china_sales(html_text: str) -> float | None:
    raw_value = _extract_china_sales_raw(html_text)
    if raw_value is None:
        return None
    match = re.search(r"([\d.]+)", raw_value)
    return float(match.group(1)) if match else None


def _extract_china_sales_raw(html_text: str) -> str | None:
    match = re.search(
        r"China\s+(?:\([^)]+\)\s+)?(?:were|totaled|was)?\s*(\$?[\d.]+\s*billion)",
        html_text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def extract_wsts_excel_download_url(
    html_text: str,
    base_url: str = "https://www.wsts.org",
) -> tuple[str, str] | None:
    """从 WSTS Historical Billings Report 页面 HTML 中提取最新 Excel 下载 URL 与文件名。"""
    soup = BeautifulSoup(html_text, "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        if "historical-billings-report" in href.lower() and href.lower().endswith(".xlsx"):
            full_url = (
                href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
            )
            filename = href.split("/")[-1]
            return full_url, filename
    return None
