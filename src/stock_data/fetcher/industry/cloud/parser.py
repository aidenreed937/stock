"""SEC EDGAR XBRL CompanyFacts 数据解析与 YTD 差分计算引擎 (extract_sec_capex)。"""

from __future__ import annotations

from datetime import date
from typing import Any

# 常见 CapEx 概念候选列表
CAPEX_XBRL_CONCEPTS: tuple[str, ...] = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForPropertyPlantAndEquipment",
)


def extract_sec_quarterly_capex(facts: dict[str, Any], ticker: str) -> dict[str, float]:
    """从 SEC XBRL CompanyFacts 中提取真实单季度资本开支 (10 亿美元)。"""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    capex_concept = None
    for cand in CAPEX_XBRL_CONCEPTS:
        if cand in us_gaap:
            capex_concept = cand
            break

    if not capex_concept:
        return {}

    units = us_gaap[capex_concept].get("units", {}).get("USD", [])
    periods: list[tuple[date, date, int, float, str]] = []
    for row in units:
        form = row.get("form")
        if form not in ("10-Q", "10-K"):
            continue
        start_str = row.get("start")
        end_str = row.get("end")
        val = float(row.get("val", 0))
        if not start_str or not end_str or val <= 0:
            continue
        try:
            d_start = date.fromisoformat(start_str)
            d_end = date.fromisoformat(end_str)
        except ValueError:
            continue
        days = (d_end - d_start).days
        periods.append((d_start, d_end, days, val, form))

    quarterly_map: dict[str, float] = {}

    # 1. 优先提取直接披露的单季发生额 (70 ~ 115 天)
    for _, d_end, days, val, _ in periods:
        if 70 <= days <= 115:
            q_num = (d_end.month - 1) // 3 + 1
            q_key = f"{d_end.year}-Q{q_num}"
            quarterly_map[q_key] = val / 1e9

    # 2. 对采用 YTD 累计披露的季度执行差分计算
    for yr in range(2016, 2027):
        q1_key = f"{yr}-Q1"
        q2_key = f"{yr}-Q2"
        q3_key = f"{yr}-Q3"
        q4_key = f"{yr}-Q4"

        # Q1
        if q1_key not in quarterly_map:
            for _, d_end, days, val, _ in periods:
                if d_end.year == yr and d_end.month in (3, 4) and days <= 115:
                    quarterly_map[q1_key] = val / 1e9
                    break

        # Q2: 半年累计 (~180天) - Q1
        if q2_key not in quarterly_map and q1_key in quarterly_map:
            for _, d_end, days, val, _ in periods:
                if d_end.year == yr and d_end.month in (6, 7) and 150 <= days <= 210:
                    q2_val = (val / 1e9) - quarterly_map[q1_key]
                    if q2_val > 0:
                        quarterly_map[q2_key] = q2_val
                    break

        # Q3: 9个月累计 (~270天) - (Q1+Q2)
        if q3_key not in quarterly_map and q1_key in quarterly_map and q2_key in quarterly_map:
            for _, d_end, days, val, _ in periods:
                if d_end.year == yr and d_end.month in (9, 10) and 240 <= days <= 300:
                    q3_val = (val / 1e9) - (quarterly_map[q1_key] + quarterly_map[q2_key])
                    if q3_val > 0:
                        quarterly_map[q3_key] = q3_val
                    break

        # Q4: 全年累计 (~365天) - (Q1+Q2+Q3)
        if (
            q4_key not in quarterly_map
            and q1_key in quarterly_map
            and q2_key in quarterly_map
            and q3_key in quarterly_map
        ):
            for _, d_end, days, val, _ in periods:
                if d_end.year == yr and d_end.month in (12, 1) and 330 <= days <= 390:
                    q4_val = (val / 1e9) - (
                        quarterly_map[q1_key] + quarterly_map[q2_key] + quarterly_map[q3_key]
                    )
                    if q4_val > 0:
                        quarterly_map[q4_key] = q4_val
                    break

    return quarterly_map
