"""TSMC 投资者月度营收页面解析器。

数据源: https://investor.tsmc.com/english/monthly-revenue/{year}
使用稳定的英文投资者页面，一次拉取可得单一年度全部 12 个月合并营收与 YoY 增速。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

# 英文月度缩写 -> 月份数字。英文页面统一使用 Sept. 而非 Sep.。
_MONTH_EN = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sept": 9,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def parse_tsmc_monthly_revenue_html(
    html_text: str, year: int | None = None
) -> list[dict[str, Any]]:
    """从 TSMC 英文投资者月度营收页面 HTML 解析全年月度合并营收。

    Args:
        html_text: 目标年度页面原始 HTML 原文。
        year: 目标年度。缺省时从页面标题 (YYYY Monthly Revenue) 提取。

    Returns:
        list[dict]，每个元素对应一个有营收数据的月份:
            report_month: "YYYY-MM"
            tsmc_revenue_ntd_million: 合并营收 (新台币百万)
            tsmc_revenue_yoy: 年度同比 (比例，如 0.359 表示 +35.9%)
    """
    target_year = year if year is not None else _extract_year(html_text)
    if target_year is None:
        return []

    rows = _extract_month_revenue_rows(html_text, target_year)
    records: list[dict[str, Any]] = []
    for month_label, net_rev_str, yoy_str in rows:
        month = _parse_month_label(month_label)
        if month is None:
            # 忽略 "Total"/"Year-to-date" 等非月度行
            continue
        net_rev = _parse_number(net_rev_str)
        if net_rev is None:
            # 未来尚未披露的月份 (当前年度下半年) 无营收，跳过
            continue
        yoy = _parse_percent(yoy_str)
        records.append(
            {
                "report_month": f"{target_year:04d}-{month:02d}",
                "tsmc_revenue_ntd_million": round(net_rev, 2),
                "tsmc_revenue_yoy": yoy,
                "month_raw": month_label,
                "net_revenue_raw": net_rev_str,
                "yoy_change_raw": yoy_str,
            }
        )

    records.sort(key=lambda r: r["report_month"])
    return records


def _extract_year(html_text: str) -> int | None:
    title = re.search(r"(\d{4})\s*Monthly\s*Revenue", html_text)
    if title is None:
        return None
    return int(title.group(1))


def _parse_month_label(raw_value: str) -> int | None:
    token = re.sub(r"[^a-zA-Z]", "", raw_value or "").lower()
    if not token:
        return None
    return _MONTH_EN.get(token)


def _parse_number(raw_value: str) -> float | None:
    digits = re.sub(r"[^\d.-]", "", raw_value or "").strip()
    if not digits or digits in {"-", "."}:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _parse_percent(raw_value: str) -> float | None:
    value = _parse_number(raw_value)
    if value is None:
        return None
    text = (raw_value or "").strip()
    return round(value / 100.0, 4) if "%" in text else round(value, 4)


class _TsmcRevenueTableParser(HTMLParser):
    """提取目标年度 basicTable 中 (月份, 营收, YoY) 三元组。

    HTML 结构 (英文投资者页面):
        <article id="tab-2025">
            <table class="basicTable ...">
                <tr><th rowspan=2>Month</th><th colspan=2>Consolidated</th></tr>
                <tr><th>Net Revenue</th><th>YoY Change</th></tr>
                <tr><td><div>Jan.</div></td><td>51,430</td><td>8.4%</td></tr>
                ...
                <tr><td><div>Total</div></td><td>...</td><td>...</td></tr>
            </table>
        </article>
    仅采集目标年度 article 内的数据行；表头 (th) 与非目标年度一律忽略。
    """

    def __init__(self) -> None:
        super().__init__()
        self.data_rows: list[list[str]] = []
        self._article_id: int | None = None
        self._in_article = False
        self._in_table = False
        self._in_row = False
        self._row_is_header = False
        self._row_cells: list[str] = []
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            attrs_dict = dict(attrs)
            self._in_article = attrs_dict.get("id") == f"tab-{self._article_id}"
            return
        if not self._in_article:
            return
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._row_is_header = False
            self._row_cells = []
        elif tag == "th" and self._in_row:
            self._row_is_header = True
        elif tag in ("td", "th") and self._in_row:
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_row:
            self._row_cells.append("".join(self._current_text).strip())
            self._current_text = []
            return
        if tag == "tr" and self._in_row:
            if not self._row_is_header and len(self._row_cells) >= 3:
                self.data_rows.append(self._row_cells)
            self._in_row = False
            return
        if tag == "table" and self._in_table:
            self._in_table = False
            return
        if tag == "article" and self._in_article:
            self._in_article = False


def _extract_month_revenue_rows(html_text: str, year: int) -> list[tuple[str, str, str]]:
    parser = _TsmcRevenueTableParser()
    parser._article_id = year  # noqa: SLF001
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 单页解析失败不阻断
        return []
    return [(row[0], row[1], row[2]) for row in parser.data_rows]
