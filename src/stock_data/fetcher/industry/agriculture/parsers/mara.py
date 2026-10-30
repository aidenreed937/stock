"""农业农村部生猪产品数据 HTML 与文本解析器。"""

from __future__ import annotations

import re
from typing import Any

from stock_data.fetcher.industry.base_parser import extract_first_float, parse_html_tables_to_rows
from stock_data.fetcher.industry.common import now_utc_iso


class MaraPorkHtmlParser:
    """农业农村部生猪产品数据月度表格页纯解析策略。"""

    def parse(self, html_text: str, **kwargs: Any) -> dict[str, Any] | None:
        """解析农业农村部生猪产品数据月度表格页。"""
        all_rows = parse_html_tables_to_rows(html_text, class_filter="data_table")
        if not all_rows:
            all_rows = parse_html_tables_to_rows(html_text)

        rows: list[tuple[str, str]] = []
        for tds in all_rows:
            if len(tds) < 2:
                continue
            if len(tds) >= 3 and tds[0].strip().isdigit():
                rows.append((tds[1], tds[2]))
            else:
                rows.append((tds[0], tds[1]))

        if not rows:
            return None

        sow_val: float | None = None
        pig_price: float | None = None
        ratio_val: float | None = None
        profit_val: float | None = None
        report_month: str | None = None

        for label, value in rows:
            if report_month is None:
                m = re.search(r"(20\d\d)\s*年\s*(?:(\d{1,2})\s*月|(\d)\s*季度)末?", label)
                if m:
                    year = int(m.group(1))
                    month = int(m.group(2)) if m.group(2) else int(m.group(3)) * 3
                    report_month = f"{year:04d}-{month:02d}"
            if "能繁母猪存栏" in label:
                raw = extract_first_float(value)
                if raw is not None:
                    sow_val = round(raw * 0.01, 2)
            elif "生猪出场价格" in label and pig_price is None:
                pig_price = extract_first_float(value)
            elif "猪粮比价" in label and ratio_val is None:
                ratio_val = extract_first_float(value)
            elif "每头净利润" in label and profit_val is None:
                profit_val = extract_first_float(value)

        if report_month is None or (sow_val is None and pig_price is None):
            return None

        return {
            "report_month": report_month,
            "sow_stock_million_heads": sow_val,
            "pig_price_cny_per_kg": pig_price,
            "hog_to_grain_ratio": ratio_val,
            "pig_farming_profit_cny_head": profit_val,
        }


def parse_mara_monthly_table(html_text: str) -> dict[str, Any] | None:
    """向后兼容的农业农村部生猪月度表格解析函数。"""
    return MaraPorkHtmlParser().parse(html_text)


def parse_mara_pork_bulletin_text(text: str) -> dict[str, Any] | None:
    """从农业农村部生猪生产通报正文中提取能繁母猪存栏、生猪出栏价与猪粮比。"""
    clean_text = text.replace(" ", "").replace("\n", "").replace("\r", "")

    sow_val: float | None = None
    m_sow = re.search(r"能繁母猪存栏(?:量)?(?:约)?(\d+\.?\d*)\s*(万头|百万头)", clean_text)
    if m_sow:
        raw_val = float(m_sow.group(1))
        unit = m_sow.group(2)
        sow_val = round(raw_val * 0.01 if unit == "万头" else raw_val, 2)

    pig_price: float | None = None
    m_price = re.search(
        r"(?:生猪|生猪出栏|全国生猪)(?:平均)?价格(?:约)?(\d+\.?\d*)\s*(?:元/公斤|元/kg)",
        clean_text,
    )
    if m_price:
        pig_price = round(float(m_price.group(1)), 2)

    ratio_val: float | None = None
    m_ratio = re.search(r"猪粮比价(?:约为|为)?(\d+\.?\d*):1?", clean_text)
    if m_ratio:
        ratio_val = round(float(m_ratio.group(1)), 2)

    if sow_val is None and pig_price is None:
        return None

    return {
        "sow_stock_million_heads": sow_val,
        "pig_price_cny_per_kg": pig_price,
        "hog_to_grain_ratio": ratio_val,
        "pig_farming_profit_cny_head": None,
        "source": "MARA/NBS",
        "source_url": "http://www.moa.gov.cn/nybgb/",
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


__all__ = [
    "MaraPorkHtmlParser",
    "parse_mara_monthly_table",
    "parse_mara_pork_bulletin_text",
]
