"""白酒批价文本解析器。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from stock_data.fetcher.industry.common import now_utc_iso

JINRIJIA_URL = "https://www.jinrijia.com/"


def parse_liquor_price_text(text: str) -> dict[str, Any] | None:
    """从白酒批价通报文本中提取茅五泸核心批价。"""
    clean_text = text.replace(" ", "").replace("\t", "")
    report_date = _extract_full_report_date(text)
    if report_date is None:
        return None

    m_loose = re.search(r"(?:散瓶|散飞|飞天散)[^\d]*(\d{4})", clean_text)
    m_boxed = re.search(r"(?:原箱|原箱飞天|整箱)[^\d]*(\d{4})", clean_text)
    m_wly = re.search(r"(?:普五|第八代五粮液|五粮液)[^\d]*(\d{3,4})", clean_text)
    m_gj = re.search(r"(?:国窖1573|国窖)[^\d]*(\d{3,4})", clean_text)

    loose_p = float(m_loose.group(1)) if m_loose else None
    boxed_p = float(m_boxed.group(1)) if m_boxed else None
    wly_p = float(m_wly.group(1)) if m_wly else None
    gj_p = float(m_gj.group(1)) if m_gj else None

    if loose_p is None and wly_p is None:
        return None

    return {
        "report_date": report_date.isoformat(),
        "trade_date": report_date,
        "moutai_loose_price_cny": loose_p,
        "moutai_boxed_price_cny": boxed_p,
        "wuliangye_puwu_price_cny": wly_p,
        "guojiao1573_price_cny": gj_p,
        "source": "TodayLiquorPrice",
        "source_url": JINRIJIA_URL,
        "release_date": None,
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


def _extract_full_report_date(text: str) -> date | None:
    match = re.search(r"(20\d{2})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


__all__ = ["JINRIJIA_URL", "parse_liquor_price_text"]
