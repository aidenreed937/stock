"""化工月频产业调研网页正文解析器（SMM 快讯 / 隆众·Mysteel 月度产量统计）。

免费月频数值源：
- 隆众/Mysteel 产量统计：样本装置产量（万吨）与本月产能利用率（%）；
- SMM 月度钛快讯：产量（万吨）、行业开工率（%，部分期次）、厂商库存（万吨，部分期次）与环比/同比。

输出遵循 ``MONTHLY_SURVEY_COLLECTION_SCHEMA`` 数值字段口径；解析失败时返回 None。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from stock_data.fetcher.industry.common import now_utc_iso

_PRODUCTION_PATTERNS = (
    r"样本装置产量(?:为)?\s*([\d.]+)\s*万吨",
    r"(?:钛白粉产量|当月产量)(?:为)?\s*([\d.]+)\s*万吨",
)
_OPERATING_RATE_PATTERNS = (
    r"本月产能利用率为\s*([\d.]+)\s*%",
    r"行业开工率达?\s*([\d.]+)\s*%",
)
_INVENTORY_ABS_PATTERN = r"厂商库存(?:达|为)?\s*([\d.]+)\s*万吨"
_MOM_WORDS = {
    "增长": 1.0,
    "增加": 1.0,
    "回升": 1.0,
    "上涨": 1.0,
    "减少": -1.0,
    "下降": -1.0,
    "回落": -1.0,
    "下跌": -1.0,
}
_YOY_WORDS = {
    "增长": 1.0,
    "增加": 1.0,
    "减少": -1.0,
    "下降": -1.0,
    "回落": -1.0,
}
_INVENTORY_MOM_PATTERN = re.compile(r"环比(增长|增加|回升|上涨|减少|下降|回落|下跌)\s*([\d.]+)\s*%")
_INVENTORY_YOY_PATTERN = re.compile(r"同比(增长|增加|减少|下降|回落)\s*([\d.]+)\s*%")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or ""))


def _first_match(patterns: tuple[str, ...], cleaned: str) -> float | None:
    for pattern in patterns:
        m = re.search(pattern, cleaned)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _inventory_segment(cleaned: str) -> str | None:
    """定位库存从句：优先‘厂商库存 X 万吨’句段，其次含‘环比/同比’的库存句。"""
    for m in re.finditer(r"厂商库存(?:达|为)?\s*[\d.]+万吨", cleaned):
        seg = cleaned[m.start() : m.end() + 120]
        if "环比" in seg or "同比" in seg:
            return seg
    for m in re.finditer(r"库存", cleaned):
        seg = cleaned[m.start() : m.end() + 120]
        if "环比" in seg or "同比" in seg:
            return seg
    return None


def _context_mom(cleaned: str, anchor: str = "库存", radius: int = 120) -> float | None:
    """从库存句式内提取环比增速（带符号），避免误取产量环比。"""
    seg = _inventory_segment(cleaned)
    if seg is None:
        return None
    m = _INVENTORY_MOM_PATTERN.search(seg)
    if m:
        return float(m.group(2)) * _MOM_WORDS[m.group(1)]
    return None


def _context_yoy(cleaned: str, anchor: str = "库存", radius: int = 120) -> float | None:
    seg = _inventory_segment(cleaned)
    if seg is None:
        return None
    m = _INVENTORY_YOY_PATTERN.search(seg)
    if m:
        return float(m.group(2)) * _YOY_WORDS[m.group(1)]
    return None


def _parse_longzhong_record(
    cleaned: str,
    *,
    report_month: str,
    source: str,
    source_url: str,
    release_date: date | None,
    symbol: str,
    product_name: str,
) -> dict[str, Any] | None:
    production = _first_match((_PRODUCTION_PATTERNS[0],), cleaned)
    op_rate = _first_match((_OPERATING_RATE_PATTERNS[0],), cleaned)
    if production is None and op_rate is None:
        return None
    return {
        "report_month": report_month,
        "product_name": product_name,
        "symbol": symbol,
        "production_w_tons": production,
        "operating_rate_pct": op_rate,
        "factory_inventory_w_tons": None,
        "inventory_mom_pct": None,
        "inventory_yoy_pct": None,
        "source": source,
        "source_url": source_url,
        "release_date": release_date,
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


def _parse_smm_record(
    cleaned: str,
    *,
    report_month: str,
    source: str,
    source_url: str,
    release_date: date | None,
    symbol: str,
    product_name: str,
) -> dict[str, Any] | None:
    production = _first_match(_PRODUCTION_PATTERNS, cleaned)
    op_rate = _first_match((_OPERATING_RATE_PATTERNS[1],), cleaned)
    inv_abs = None
    m_inv = re.search(_INVENTORY_ABS_PATTERN, cleaned)
    if m_inv:
        try:
            inv_abs = float(m_inv.group(1))
        except ValueError:
            inv_abs = None
    inv_mom = _context_mom(cleaned)
    inv_yoy = _context_yoy(cleaned)
    if production is None and op_rate is None and inv_abs is None:
        return None
    return {
        "report_month": report_month,
        "product_name": product_name,
        "symbol": symbol,
        "production_w_tons": production,
        "operating_rate_pct": op_rate,
        "factory_inventory_w_tons": inv_abs,
        "inventory_mom_pct": inv_mom,
        "inventory_yoy_pct": inv_yoy,
        "source": source,
        "source_url": source_url,
        "release_date": release_date,
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


def parse_monthly_survey_record(
    text: str,
    *,
    report_month: str,
    source: str,
    source_url: str,
    release_date: date | None,
    symbol: str = "TiO2",
    product_name: str = "钛白粉",
) -> dict[str, Any] | None:
    """按来源分发解析月频调研正文；无法提取有效指标时返回 None。"""
    cleaned = _clean_text(text)
    if not cleaned:
        return None
    kwargs: dict[str, Any] = {
        "report_month": report_month,
        "source": source,
        "source_url": source_url,
        "release_date": release_date,
        "symbol": symbol,
        "product_name": product_name,
    }
    if source.upper().startswith("SMM"):
        return _parse_smm_record(cleaned, **kwargs)
    return _parse_longzhong_record(cleaned, **kwargs)


def has_monthly_metrics(record: dict[str, Any]) -> bool:
    """判断记录是否至少包含一个有效月频指标。"""
    return any(
        record.get(key) is not None
        for key in (
            "production_w_tons",
            "operating_rate_pct",
            "factory_inventory_w_tons",
            "inventory_mom_pct",
            "inventory_yoy_pct",
        )
    )


__all__ = ["has_monthly_metrics", "parse_monthly_survey_record"]
