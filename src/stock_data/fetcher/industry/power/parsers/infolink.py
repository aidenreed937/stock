"""InfoLink 光伏价格 HTML 解析器。"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from stock_data.fetcher.industry.base_parser import (
    HtmlParserProtocol,
    extract_first_float,
    parse_html_tables_to_rows,
)

logger = logging.getLogger(__name__)

INFOLINK_SPOT_PRICE_URL = "https://www.infolink-group.com/spot-price/cn/"


def _normalize_reference_year(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        year = int(value)
    except ValueError:
        return None
    return year if 2000 <= year <= 2100 else None


class InfoLinkSpotPriceHtmlParser(HtmlParserProtocol[dict[str, Any]]):
    """InfoLink Consulting 官方光伏现货报价页面 HTML 纯解析策略。"""

    def parse(
        self,
        html_text: str,
        source_url: str = "",
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """从 InfoLink 官方光伏现货报价页面 HTML 中高精度抽取各环节均价与发布日期。"""
        if "多晶硅" not in html_text and "硅片" not in html_text and "组件" not in html_text:
            return None

        trade_d: date | None = None
        rep_date: str | None = None
        match_art_date = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", html_text)
        if match_art_date is None:
            match_art_date = re.search(r"pv-spot-price-(20\d{2})(\d{2})(\d{2})", source_url)
        if match_art_date:
            y, m, d = [int(x) for x in match_art_date.groups()]
            try:
                trade_d = date(y, m, d)
                rep_date = trade_d.isoformat()
            except ValueError:
                pass
        else:
            reference_year = _normalize_reference_year(kwargs.get("reference_year"))
            match_range = re.search(r"\((\d{1,2})\.(\d{1,2})-(\d{1,2})\.(\d{1,2})\)", html_text)
            if match_range and reference_year is not None:
                _, _, m2, d2 = [int(x) for x in match_range.groups()]
                try:
                    trade_d = date(reference_year, m2, d2)
                    rep_date = trade_d.isoformat()
                except ValueError:
                    pass

        if trade_d is None or rep_date is None:
            logger.warning("InfoLink 报价页未解析出有效发布日期，放弃本次抓取")
            return None

        results: dict[str, Any] = {
            "report_date": rep_date,
            "trade_date": trade_d,
            "polysilicon_price_cny_kg": None,
            "wafer_price_cny_piece": None,
            "cell_price_cny_watt": None,
            "module_price_cny_watt": None,
            "price_cycle_stage": None,
            "source": "InfoLink Consulting",
            "source_url": source_url or INFOLINK_SPOT_PRICE_URL,
            "release_date": None,
            "data_status": "actual",
            "collected_at": datetime.now(UTC).isoformat(),
        }

        all_rows = parse_html_tables_to_rows(html_text)
        for cells in all_rows:
            if len(cells) >= 4:
                item_name = cells[0]
                avg_val = extract_first_float(cells[3])
                if avg_val is None:
                    continue
                if "多晶硅" in item_name and "致密料" in item_name and "(RMB)" in item_name:
                    results["polysilicon_price_cny_kg"] = avg_val
                elif "硅片" in item_name and "182" in item_name and "(RMB)" in item_name:
                    if results["wafer_price_cny_piece"] is None:
                        results["wafer_price_cny_piece"] = avg_val
                elif (
                    "电池片" in item_name
                    and ("TOPCon" in item_name or "182" in item_name)
                    and "(RMB)" in item_name
                ):
                    if results["cell_price_cny_watt"] is None:
                        results["cell_price_cny_watt"] = avg_val
                elif (
                    "组件" in item_name
                    and ("TOPCon" in item_name or "182" in item_name)
                    and "(RMB)" in item_name
                ):
                    if results["module_price_cny_watt"] is None:
                        results["module_price_cny_watt"] = avg_val

        # 历史文章页使用叙述文本而不是价格表，保留文章原文中明确披露的均价。
        text = re.sub(r"\s+", "", html_text)
        if results["polysilicon_price_cny_kg"] is None:
            match = re.search(r"致密(?:复投)?料(?:报价|均价)(?:约|为)?每公斤([\d.]+)元", text)
            if match:
                results["polysilicon_price_cny_kg"] = float(match.group(1))
        if results["wafer_price_cny_piece"] is None:
            section = _section_text(text, "硅片价格", "中国电池片价格")
            match = re.search(r"每片([\d.]+)元人民币", section)
            if match:
                results["wafer_price_cny_piece"] = float(match.group(1))
        if results["cell_price_cny_watt"] is None:
            section = _section_text(text, "中国电池片价格", "海外电池片价格")
            match = re.search(r"均价(?:下跌|上涨|维持)?至?每瓦([\d.]+)元", section)
            if match is None:
                match = re.search(r"均价(?:落在|为|持平于)?每瓦([\d.]+)元", section)
            if match:
                results["cell_price_cny_watt"] = float(match.group(1))
        if results["module_price_cny_watt"] is None:
            section = _section_text(text, "组件价格", "海外组件价格")
            match = re.search(r"TOPCon组件实际交付价格[^每]*每瓦([\d.]+)-([\d.]+)元人民币", section)
            if match:
                results["module_price_cny_watt"] = round(
                    (float(match.group(1)) + float(match.group(2))) / 2.0, 4
                )
            else:
                match = re.search(r"均价落在每瓦([\d.]+)元人民币", section)
                if match:
                    results["module_price_cny_watt"] = float(match.group(1))

        if (
            results["polysilicon_price_cny_kg"] is None
            and results["wafer_price_cny_piece"] is None
            and results["cell_price_cny_watt"] is None
            and results["module_price_cny_watt"] is None
        ):
            return None

        return results


def _section_text(text: str, start_marker: str, end_marker: str) -> str:
    """截取文章中一个价格章节的纯文本。"""
    start = text.find(start_marker)
    if start < 0:
        return text
    end = text.find(end_marker, start + len(start_marker))
    return text[start:] if end < 0 else text[start:end]


def parse_infolink_spot_price_html(html_text: str, source_url: str = "") -> dict[str, Any] | None:
    """从 InfoLink Consulting 官方光伏现货报价页面 HTML 中抽取各环节均价。"""
    return InfoLinkSpotPriceHtmlParser().parse(html_text, source_url=source_url)


__all__ = [
    "INFOLINK_SPOT_PRICE_URL",
    "InfoLinkSpotPriceHtmlParser",
    "parse_infolink_spot_price_html",
]
