"""国家能源局 (NEA) 电力统计通报与 HTML 表格解析器。"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from stock_data.fetcher.energy.cn_nea.constants import NEA_TABLE_INDICATOR_MAPPING

logger = logging.getLogger(__name__)


def clean_num_string(val_str: str | None) -> float | None:
    """清洗数值字符串，去除 '*'、'▲'、空格、逗号等符号。"""
    if not val_str:
        return None
    cleaned = (
        val_str.replace("*", "")
        .replace("▲", "")
        .replace(" ", "")
        .replace(",", "")
        .replace("，", "")
        .replace("%", "")
        .replace("％", "")
        .strip()
    )
    if not cleaned or cleaned in ("-", "--", "/", "—"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_period_from_title(title_or_text: str) -> tuple[str | None, int | None]:
    """从通报标题或文本中提取 YYYY-MM 和月份数字。"""
    clean_title = title_or_text.replace(" ", "")
    m_full = re.search(r"(\d{4})年(?:1-)?(\d{1,2})月份?", clean_title)
    if m_full:
        year = int(m_full.group(1))
        month = int(m_full.group(2))
        return f"{year:04d}-{month:02d}", month

    # 匹配年度通报 (如: 2023年全国电力工业统计数据 -> 2023-12)
    m_year_full = re.search(r"(\d{4})年(?:度)?(?:全国)?(?:电力|全社会用电量)", clean_title)
    if m_year_full:
        year = int(m_year_full.group(1))
        return f"{year:04d}-12", 12

    m_short = re.search(r"(?:1-)?(\d{1,2})月份?全国电力", clean_title)
    if m_short:
        month = int(m_short.group(1))
        return None, month

    return None, None


def extract_release_date_from_html(soup: BeautifulSoup) -> date | None:
    """从 HTML 页面中提取官方发布日期。"""
    date_pattern = re.compile(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})")
    for text in soup.stripped_strings:
        if "发布时间" in text or "时间：" in text or "来源：" in text:
            m = date_pattern.search(text)
            if m:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    all_text = soup.get_text()[:2000]
    m = date_pattern.search(all_text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _match_text_metric(
    text: str,
    name: str,
    pattern: str,
    yoy_pattern: str,
    indicators: dict[str, dict[str, Any]],
    unit: str = "万千瓦",
) -> None:
    """从通报文本段落中提取单项指标。"""
    m = re.search(pattern, text)
    if not m:
        return
    raw_val = float(m.group(1))
    if len(m.groups()) > 1:
        u = m.group(2)
        if u == "亿千瓦":
            val = raw_val * 10000.0
        elif u in ("吉瓦", "GW"):
            val = raw_val * 100.0
        else:
            val = raw_val
    else:
        val = raw_val

    yoy_val: float | None = None
    m_yoy = re.search(yoy_pattern, text)
    if m_yoy:
        yoy_val = round(float(m_yoy.group(1)) / 100.0, 4)

    indicators[name] = {
        "indicator_name": name,
        "section": "TEXT_EXTRACTED",
        "cumulative_value": val,
        "unit": unit,
        "yoy_growth": yoy_val,
    }


def parse_nea_text_fallback(full_text: str) -> dict[str, dict[str, Any]]:
    """从通报文本段落中正则匹配关键核心装机与利用小时数据 (降级提取)。"""
    indicators: dict[str, dict[str, Any]] = {}
    clean_text = full_text.replace(" ", "").replace("\n", "").replace("\r", "")

    # 太阳能、风电、总装机、电网、电源投资
    _match_text_metric(
        clean_text,
        name="太阳能发电",
        pattern=r"太阳能发电装机容量(?:约)?(\d+\.?\d*)\s*(亿千瓦|万千瓦|吉瓦|GW)",
        yoy_pattern=r"太阳能发电装机容量[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        indicators=indicators,
    )
    _match_text_metric(
        clean_text,
        name="风电",
        pattern=r"风电装机容量(?:约)?(\d+\.?\d*)\s*(亿千瓦|万千瓦|吉瓦|GW)",
        yoy_pattern=r"风电装机容量[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        indicators=indicators,
    )
    _match_text_metric(
        clean_text,
        name="全国发电装机容量",
        pattern=r"全国累计发电装机容量(?:约)?(\d+\.?\d*)\s*(亿千瓦|万千瓦|吉瓦|GW)",
        yoy_pattern=r"全国累计发电装机容量[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        indicators=indicators,
    )
    _match_text_metric(
        clean_text,
        name="电网工程投资完成",
        pattern=r"电网工程完成投资(?:约)?(\d+\.?\d*)\s*亿元",
        yoy_pattern=r"电网工程完成投资[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        indicators=indicators,
        unit="亿元",
    )
    _match_text_metric(
        clean_text,
        name="电源工程投资完成",
        pattern=r"电源工程完成投资(?:约)?(\d+\.?\d*)\s*亿元",
        yoy_pattern=r"电源工程完成投资[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        indicators=indicators,
        unit="亿元",
    )
    _match_text_metric(
        clean_text,
        name="全国发电设备累计平均利用小时",
        pattern=r"全国发电设备累计平均利用(?:约)?(\d+\.?\d*)\s*小时",
        yoy_pattern=r"全国发电设备累计平均利用[^\d]*\d+\.?\d*小时[^，。]*[，,]比上年同期(?:降低|减少|增加)?(\d+\.?\d*)小时",
        indicators=indicators,
        unit="小时",
    )
    return indicators


class NeaPowerTableParser:
    """国家能源局《全国电力工业统计数据一览表》双模解析器。"""

    @classmethod
    def parse_html(cls, html_content: str, source_url: str = "") -> dict[str, Any] | None:
        """解析国家能源局通报 HTML，优先解析表格，无表格则降级为正文正则。"""
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        title_el = soup.find(["h1", "title", "h2"])
        title_text = title_el.get_text(strip=True) if title_el else ""

        period_str, month_num = extract_period_from_title(title_text)
        release_date = extract_release_date_from_html(soup)

        if not period_str and month_num and release_date:
            year = release_date.year
            if release_date.month == 1 and month_num == 12:
                year -= 1
            period_str = f"{year:04d}-{month_num:02d}"

        # 1. 优先尝试解析 HTML Table
        table_indicators = cls._parse_table(soup)

        # 2. 若表格为空，尝试正文文本正则提取 (降级容错)
        if not table_indicators:
            logger.debug("未在通报中找到规范 HTML 表格，启用正文正则降级: %s", title_text)
            table_indicators = parse_nea_text_fallback(soup.get_text())

        if not table_indicators or not period_str:
            logger.warning("未能有效解析通报指标或时间周期: %s (url: %s)", title_text, source_url)
            return None

        return {
            "title": title_text,
            "period": period_str,
            "month": month_num or int(period_str.split("-")[1]),
            "release_date": release_date,
            "source_url": source_url,
            "indicators": table_indicators,
        }

    @classmethod
    def _parse_table(cls, soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
        """解析《全国电力工业统计数据一览表》HTML Table。"""
        indicators: dict[str, dict[str, Any]] = {}
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue

            current_section = ""
            for tr in rows:
                cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if not cols:
                    continue

                col0 = cols[0]
                if "装机容量" in col0 and "新增" not in col0:
                    current_section = "CAPACITY"
                elif "利用小时" in col0:
                    current_section = "UTILIZATION"
                elif "投资完成" in col0:
                    current_section = "INVESTMENT"
                elif "新增" in col0 and "装机" in col0:
                    current_section = "NEW_CAPACITY"

                matched_key = next(
                    (
                        c
                        for c in NEA_TABLE_INDICATOR_MAPPING
                        if c == col0 or (len(col0) > 2 and c in col0)
                    ),
                    None,
                )
                if not matched_key:
                    continue

                unit = (
                    cols[1]
                    if len(cols) > 1
                    and cols[1] in ("万千瓦", "小时", "亿元", "亿千瓦时", "%", "克/千瓦时")
                    else ""
                )
                val_idx = 2 if unit else 1
                if len(cols) > val_idx:
                    cum_val = clean_num_string(cols[val_idx])
                    yoy_val = clean_num_string(cols[-1]) if len(cols) > val_idx + 1 else None
                    yoy_ratio = round(yoy_val / 100.0, 4) if yoy_val is not None else None

                    indicators[matched_key] = {
                        "indicator_name": matched_key,
                        "section": current_section,
                        "cumulative_value": cum_val,
                        "unit": unit or NEA_TABLE_INDICATOR_MAPPING[matched_key][2],
                        "yoy_growth": yoy_ratio,
                    }

        return indicators
