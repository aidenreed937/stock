"""SEC EDGAR XBRL CompanyFacts 数据解析与 YTD 差分计算引擎 (extract_sec_capex)。"""

from __future__ import annotations

from datetime import date
from typing import Any

# 常见 CapEx 概念候选列表 (按优先级排序)
CAPEX_XBRL_CONCEPTS: tuple[str, ...] = (
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForPropertyPlantAndEquipment",
)


def extract_sec_quarterly_capex(facts: dict[str, Any], ticker: str) -> dict[str, float]:
    """从 SEC XBRL CompanyFacts 中提取真实单季度资本开支 (10 亿美元)。"""
    return {
        quarter: value
        for quarter, (value, _filing_date) in extract_sec_quarterly_capex_with_filing_dates(
            facts, ticker
        ).items()
    }


def extract_sec_quarterly_capex_with_filing_dates(
    facts: dict[str, Any], ticker: str
) -> dict[str, tuple[float, date | None]]:
    """提取真实单季度资本开支及其 SEC filingDate。"""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    periods: list[tuple[date, date, int, float, str, date | None]] = []
    seen_keys: set[tuple[date, date]] = set()

    # 遍历所有存在的 CapEx 概念并合并期间 (按概念优先级去重)
    for cand in CAPEX_XBRL_CONCEPTS:
        if cand not in us_gaap:
            continue
        units = us_gaap[cand].get("units", {}).get("USD", [])
        for row in units:
            form = row.get("form")
            if form not in ("10-Q", "10-K"):
                continue
            start_str = row.get("start")
            end_str = row.get("end")
            raw_val = row.get("val")
            if raw_val is None:
                continue
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                continue
            if not start_str or not end_str or val <= 0:
                continue
            try:
                d_start = date.fromisoformat(start_str)
                d_end = date.fromisoformat(end_str)
            except ValueError:
                continue
            filed_str = row.get("filed")
            try:
                filed_date = date.fromisoformat(filed_str) if filed_str else None
            except (TypeError, ValueError):
                filed_date = None
            key = (d_start, d_end)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            days = (d_end - d_start).days
            periods.append((d_start, d_end, days, val, form, filed_date))

    if not periods:
        return {}

    quarterly_map: dict[str, tuple[float, date | None]] = {}

    # 1. 优先提取直接披露的单季发生额 (70 ~ 115 天)
    for _, d_end, days, val, _, filed_date in periods:
        if 70 <= days <= 115:
            q_num = (d_end.month - 1) // 3 + 1
            q_key = f"{d_end.year}-Q{q_num}"
            quarterly_map[q_key] = (val / 1e9, filed_date)

    # 2. 对采用 YTD 累计披露的季度执行差分计算。年份边界从事实期末动态推导，
    # 避免固定上限导致后续季度增量静默丢失。
    first_year = min(2016, *(period[1].year for period in periods))
    last_year = max(2026, *(period[1].year for period in periods))
    for yr in range(first_year, last_year + 1):
        q1_key = f"{yr}-Q1"
        q2_key = f"{yr}-Q2"
        q3_key = f"{yr}-Q3"
        q4_key = f"{yr}-Q4"

        # Q1: 直接发生额或 <= 115 天
        if q1_key not in quarterly_map:
            for _, d_end, days, val, _, filed_date in periods:
                if d_end.year == yr and d_end.month in (3, 4) and days <= 115:
                    quarterly_map[q1_key] = (val / 1e9, filed_date)
                    break

        # Q2 (自然年财年): 半年累计 (~180天) - Q1
        if q2_key not in quarterly_map and q1_key in quarterly_map:
            for _, d_end, days, val, _, filed_date in periods:
                if d_end.year == yr and d_end.month in (6, 7) and 150 <= days <= 210:
                    q2_val = (val / 1e9) - quarterly_map[q1_key][0]
                    if q2_val > 0:
                        quarterly_map[q2_key] = (q2_val, filed_date)
                    break

        # Q2 (6月30日结财年, 如 MSFT): 12个月全年 (10-K) - 前9个月累计 (Q3 10-Q)
        if q2_key not in quarterly_map:
            fy_12m: tuple[float, date | None] | None = None
            ytd_9m: tuple[float, date | None] | None = None
            for _, d_end, days, val, _, filed_date in periods:
                if d_end.year == yr and d_end.month in (6, 7) and 330 <= days <= 390:
                    fy_12m = (val / 1e9, filed_date)
                if d_end.year == yr and d_end.month in (3, 4) and 240 <= days <= 300:
                    ytd_9m = (val / 1e9, filed_date)
            if fy_12m is not None and ytd_9m is not None:
                q2_val = fy_12m[0] - ytd_9m[0]
                if q2_val > 0:
                    quarterly_map[q2_key] = (q2_val, fy_12m[1])

        # Q3: 9个月累计 (~270天) - (Q1+Q2)
        if q3_key not in quarterly_map and q1_key in quarterly_map and q2_key in quarterly_map:
            for _, d_end, days, val, _, filed_date in periods:
                if d_end.year == yr and d_end.month in (9, 10) and 240 <= days <= 300:
                    q3_val = (val / 1e9) - (quarterly_map[q1_key][0] + quarterly_map[q2_key][0])
                    if q3_val > 0:
                        quarterly_map[q3_key] = (q3_val, filed_date)
                    break

        # Q4 (12月31日结财年): 全年累计 (~365天) - (Q1+Q2+Q3)
        if (
            q4_key not in quarterly_map
            and q1_key in quarterly_map
            and q2_key in quarterly_map
            and q3_key in quarterly_map
        ):
            for _, d_end, days, val, _, filed_date in periods:
                if d_end.year == yr and d_end.month in (12, 1) and 330 <= days <= 390:
                    q4_val = (val / 1e9) - (
                        quarterly_map[q1_key][0]
                        + quarterly_map[q2_key][0]
                        + quarterly_map[q3_key][0]
                    )
                    if q4_val > 0:
                        quarterly_map[q4_key] = (q4_val, filed_date)
                    break

    return quarterly_map
