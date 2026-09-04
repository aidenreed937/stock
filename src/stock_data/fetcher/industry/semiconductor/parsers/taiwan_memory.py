"""台湾存储龙头 (南亚科/威刚) 月度营运营收解析器。

数据源:
- 台湾公开资讯观测站 (MOPS) / 官方投资者关系月度营收数据
- 遵循与 TSMC 相同的月度营收披露规范 (每月 10 日前披露上月合并营收)

保留源端原始字符串与字段 (company_name_raw, net_revenue_raw, yoy_change_raw 等)。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.semiconductor.models import TaiwanMemoryLeadRecord

logger = logging.getLogger(__name__)

# 台湾代表性存储龙头公司元数据
TAIWAN_MEMORY_COMPANIES = {
    "2408": {"name": "南亚科技", "full_name": "南亞科技股份有限公司", "role": "DRAM_IDM"},
    "3260": {"name": "威刚科技", "full_name": "威剛科技股份有限公司", "role": "MODULE"},
}


def parse_taiwan_memory_monthly_revenue_dict(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    source_url: str = "",
    collected_at: str = "",
    raw_content_sha256: str = "",
    raw_snapshot_path: str = "",
) -> list[TaiwanMemoryLeadRecord]:
    """从结构化字典行中解析台湾存储龙头的月度营运营收记录。

    每一行可包含:
        report_month / report_month_raw: "YYYY-MM" 或 "113/07" 等
        net_revenue_raw: 当月营收原始字符串 (可能含逗号)
        last_year_revenue_raw: 去年同月营收原始字符串
        yoy_change_raw: 同比增减原始字符串 (如 "12.34%")
        mom_change_raw: 环比增减原始字符串 (如 "-1.23%")
    """
    collect_time = collected_at or now_utc_iso()
    meta = TAIWAN_MEMORY_COMPANIES.get(symbol, {"name": symbol, "full_name": symbol})
    company_name = meta["name"]
    records: list[TaiwanMemoryLeadRecord] = []

    for row in rows:
        month_raw = str(row.get("report_month_raw") or row.get("report_month") or "").strip()
        report_month = _normalize_taiwan_report_month(month_raw)
        if not report_month:
            continue

        year, month = parse_month_string(report_month)
        trade_date = get_month_end_date(year, month)
        release_date_raw = _source_value(row.get("release_date_raw"))
        release_date = _parse_mops_release_date(release_date_raw)
        if release_date is not None:
            release_date_status = "reported"
        else:
            release_date_status = "unavailable" if release_date_raw is None else "invalid"
        response_datetime_raw = _source_value(row.get("source_response_datetime_raw"))

        net_rev_raw = str(row.get("net_revenue_raw") or row.get("revenue") or "").strip()
        revenue_thousand = _parse_taiwan_revenue_source(net_rev_raw)
        if revenue_thousand is None:
            continue

        yoy_raw = str(row.get("yoy_change_raw") or row.get("yoy") or "").strip()
        yoy = _parse_percent(yoy_raw) if yoy_raw else None

        mom_raw = str(row.get("mom_change_raw") or row.get("mom") or "").strip()
        mom = _parse_percent(mom_raw) if mom_raw else None

        records.append(
            TaiwanMemoryLeadRecord(
                report_month=report_month,
                trade_date=trade_date,
                symbol=symbol,
                company_name=company_name,
                revenue_ntd_thousand=revenue_thousand,
                revenue_yoy=yoy,
                revenue_mom=mom,
                unit="thousand_ntd",
                source="MOPS",
                source_url=source_url,
                release_date=release_date,
                release_date_raw=release_date_raw,
                release_date_status=release_date_status,
                source_response_datetime_raw=response_datetime_raw,
                data_status="actual",
                collected_at=collect_time,
                raw_content_sha256=raw_content_sha256,
                raw_snapshot_path=raw_snapshot_path,
                company_name_raw=str(row.get("company_name_raw") or meta.get("full_name") or ""),
                report_month_raw=month_raw,
                net_revenue_raw=net_rev_raw,
                last_year_revenue_raw=str(row.get("last_year_revenue_raw") or ""),
                yoy_change_raw=yoy_raw,
                mom_change_raw=mom_raw,
                cumulative_revenue_raw=str(row.get("cumulative_revenue_raw") or ""),
                cumulative_yoy_raw=str(row.get("cumulative_yoy_raw") or ""),
            )
        )

    return sorted(records, key=lambda r: (r.symbol, r.report_month))


def _normalize_taiwan_report_month(month_raw: str) -> str | None:
    """标准化台湾月度日期，支持西元 '2024-07'、'202407' 及民国年 '113/07'、'113年7月'、'11307'。"""
    cleaned = str(month_raw).strip()
    # 匹配西元年 YYYY-MM 或 YYYY/MM
    match_ce = re.match(r"^(\d{4})[-/.]?(\d{2})$", cleaned)
    if match_ce:
        yr = int(match_ce.group(1))
        mo = int(match_ce.group(2))
        if 1 <= mo <= 12:
            return f"{yr:04d}-{mo:02d}"

    # 匹配民国年 ROC year (如 113/07, 113/7)
    match_roc = re.match(r"^(\d{2,3})[年/-](\d{1,2})", cleaned)
    if match_roc:
        roc_yr = int(match_roc.group(1))
        mo = int(match_roc.group(2))
        yr = roc_yr + 1911
        if 1 <= mo <= 12:
            return f"{yr:04d}-{mo:02d}"

    # 匹配无分隔符纯数字民国年月 (如 11307, 11508)
    if len(cleaned) == 5 and cleaned.isdigit():
        roc_yr = int(cleaned[:3])
        mo = int(cleaned[3:])
        yr = roc_yr + 1911
        if 1 <= mo <= 12:
            return f"{yr:04d}-{mo:02d}"

    return None


def _source_value(value: Any) -> str | None:
    """将源端可选字段保留为非空原始字符串。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_mops_release_date(raw_value: str | None) -> date | None:
    """解析 MOPS 响应顶层 datetime，支持民国年和 ISO 日期格式。"""
    if not raw_value:
        return None
    text = raw_value.strip()
    roc_match = re.match(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if roc_match:
        year, month, day = (int(value) for value in roc_match.groups())
        if year < 1911:
            year += 1911
        try:
            return date(year, month, day)
        except ValueError:
            return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_taiwan_revenue_source(raw_value: str) -> float | None:
    """解析 MOPS 营收源值；MOPS 营收栏固定以千元新台币提供。"""
    digits = re.sub(r"[^\d.-]", "", str(raw_value or "")).strip()
    if not digits or digits in {"-", "."}:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _parse_percent(raw_value: str) -> float | None:
    digits = re.sub(r"[^\d.-]", "", str(raw_value or "")).strip()
    if not digits or digits in {"-", "."}:
        return None
    try:
        val = float(digits)
        # MOPS 的「增減百分比」源值通常不带百分号，数值本身仍以百分数表示。
        return round(val / 100.0, 4)
    except ValueError:
        return None
