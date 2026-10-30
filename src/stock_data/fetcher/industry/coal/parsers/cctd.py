"""CCTD 动力煤价格 HTML 解析器。"""

from __future__ import annotations

import re
from typing import Any


class CctdCoalPriceHtmlParser:
    """CCTD 秦皇岛动力煤价格页 HTML 纯解析策略。"""

    def parse(self, html_text: str, **kwargs: Any) -> dict[str, Any] | None:
        """从 CCTD 秦皇岛动力煤价格页提取 CCTD 综合交易 5500 平仓价。"""
        idx = html_text.find("本期值")
        if idx < 0:
            return None
        segment = html_text[idx : idx + 300]
        m_price = re.search(r"<em[^>]*>\s*([\d.]+)\s*</em>", segment)
        if not m_price:
            return None
        m_mom = re.search(r"较上期.*?<em[^>]*>\s*([-\d.]+)\s*</em>", segment, re.DOTALL)
        m_date = re.search(r"日期：(\d{4}-\d{2}-\d{2})", html_text)
        if not m_date:
            return None
        return {
            "report_date": m_date.group(1),
            "q5500_fob_price_cny": float(m_price.group(1)),
            "q5500_mom": float(m_mom.group(1)) if m_mom else None,
        }


def parse_cctd_q5500(html_text: str) -> dict[str, Any] | None:
    """向后兼容的 CCTD 动力煤价格提取函数。"""
    return CctdCoalPriceHtmlParser().parse(html_text)


__all__ = ["CctdCoalPriceHtmlParser", "parse_cctd_q5500"]
