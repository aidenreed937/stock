"""SEC EDGAR XBRL CompanyFacts 数据解析与 YTD 差分计算引擎。"""

from __future__ import annotations

from datetime import date
from typing import Any

# 常见 CapEx 概念候选列表 (按优先级排序)
CAPEX_XBRL_CONCEPTS: tuple[str, ...] = (
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForPropertyPlantAndEquipment",
)

REVENUE_XBRL_CONCEPTS: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)

OPERATING_CASH_FLOW_XBRL_CONCEPTS: tuple[str, ...] = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)

_SEC_FILING_FORMS = frozenset(("10-Q", "10-K", "10-Q/A", "10-K/A"))


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
    return extract_sec_quarterly_metric_with_filing_dates(
        facts,
        ticker,
        CAPEX_XBRL_CONCEPTS,
        positive_only=True,
    )


def extract_sec_quarterly_metric_with_filing_dates(
    facts: dict[str, Any],
    ticker: str,
    concepts: tuple[str, ...],
    *,
    positive_only: bool = False,
) -> dict[str, tuple[float, date | None]]:
    """提取 CompanyFacts 中的季度金额，并将 YTD 累计值差分为单季值。

    ``ticker`` 保留在接口中，便于调用方统一传递标的并与既有 CapEx 解析器兼容。
    CompanyFacts 同一期间可能同时出现单季、半年累计和多个概念；优先使用概念列表
    前面的字段，并在同一概念内保留首次有效 filing。后续 10-Q/10-K 比较期记录不应
    改写原始披露日期；如果没有原始申报，则允许使用最早的 10-Q/A 或 10-K/A 记录。
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    periods_by_key: dict[tuple[date, date], tuple[int, float, date | None]] = {}

    for priority, cand in enumerate(concepts):
        if cand not in us_gaap:
            continue
        units = us_gaap[cand].get("units", {}).get("USD", [])
        for row in units:
            form = row.get("form")
            if form not in _SEC_FILING_FORMS:
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
            if not start_str or not end_str or (positive_only and val <= 0):
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
            candidate = (priority, val, filed_date)
            previous = periods_by_key.get(key)
            if (
                previous is None
                or priority < previous[0]
                or (priority == previous[0] and _is_earlier_filing(filed_date, previous[2]))
            ):
                periods_by_key[key] = candidate

    periods = [
        (d_start, d_end, (d_end - d_start).days, value[1], value[2])
        for (d_start, d_end), value in periods_by_key.items()
    ]

    if not periods:
        return {}

    quarterly_map: dict[str, tuple[float, date | None]] = {}

    def put(quarter: str, value: float, filed_date: date | None) -> None:
        if positive_only and value <= 0:
            return
        previous = quarterly_map.get(quarter)
        previous_date = previous[1] if previous is not None else None
        if previous is None or _is_earlier_filing(filed_date, previous_date):
            quarterly_map[quarter] = (value, filed_date)

    def period_value(
        *, year: int, end_months: tuple[int, ...], min_days: int, max_days: int
    ) -> tuple[float, date | None] | None:
        candidates = [
            (value, filed_date)
            for _start, end, days, value, filed_date in periods
            if end.year == year and end.month in end_months and min_days <= days <= max_days
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: _filing_sort_key(item[1]))

    # 1. 优先提取直接披露的单季发生额 (70 ~ 115 天)
    for _, d_end, days, val, filed_date in periods:
        if 70 <= days <= 115:
            q_num = (d_end.month - 1) // 3 + 1
            q_key = f"{d_end.year}-Q{q_num}"
            put(q_key, val / 1e9, filed_date)

    # 2. 对采用 YTD 累计披露的季度执行差分计算。
    first_year = min(period[1].year for period in periods)
    last_year = max(period[1].year for period in periods)
    for yr in range(first_year, last_year + 1):
        q1_key = f"{yr}-Q1"
        q2_key = f"{yr}-Q2"
        q3_key = f"{yr}-Q3"
        q4_key = f"{yr}-Q4"

        # Q1: 直接发生额或 <= 115 天
        if q1_key not in quarterly_map:
            q1 = period_value(year=yr, end_months=(3, 4), min_days=1, max_days=115)
            if q1 is not None:
                put(q1_key, q1[0] / 1e9, q1[1])

        # Q2 (自然年财年): 半年累计 (~180天) - Q1
        if q2_key not in quarterly_map and q1_key in quarterly_map:
            ytd = period_value(year=yr, end_months=(6, 7), min_days=150, max_days=210)
            if ytd is not None:
                q2_val = ytd[0] / 1e9 - quarterly_map[q1_key][0]
                put(q2_key, q2_val, ytd[1])

        # Q2 (6月30日结财年, 如 MSFT): 12个月全年 (10-K) - 前9个月累计 (Q3 10-Q)
        if q2_key not in quarterly_map:
            fy_12m = period_value(year=yr, end_months=(6, 7), min_days=330, max_days=390)
            ytd_9m = period_value(year=yr, end_months=(3, 4), min_days=240, max_days=300)
            if fy_12m is not None and ytd_9m is not None:
                q2_val = (fy_12m[0] - ytd_9m[0]) / 1e9
                filed_date = max(fy_12m[1] or date.min, ytd_9m[1] or date.min)
                put(q2_key, q2_val, None if filed_date == date.min else filed_date)

        # Q3: 9个月累计 (~270天) - (Q1+Q2)
        if q3_key not in quarterly_map and q1_key in quarterly_map and q2_key in quarterly_map:
            ytd = period_value(year=yr, end_months=(9, 10), min_days=240, max_days=300)
            if ytd is not None:
                q3_val = ytd[0] / 1e9 - (quarterly_map[q1_key][0] + quarterly_map[q2_key][0])
                put(q3_key, q3_val, ytd[1])

        # Q4 (12月31日结财年): 全年累计 (~365天) - (Q1+Q2+Q3)
        if (
            q4_key not in quarterly_map
            and q1_key in quarterly_map
            and q2_key in quarterly_map
            and q3_key in quarterly_map
        ):
            annual = period_value(year=yr, end_months=(12, 1), min_days=330, max_days=390)
            if annual is not None:
                q4_val = annual[0] / 1e9 - (
                    quarterly_map[q1_key][0] + quarterly_map[q2_key][0] + quarterly_map[q3_key][0]
                )
                put(q4_key, q4_val, annual[1])

    return quarterly_map


def _filing_sort_key(filed_date: date | None) -> tuple[bool, date]:
    """让有日期的申报优先，并在其中选择最早 filed 日期。"""
    return (filed_date is None, filed_date or date.max)


def _is_earlier_filing(candidate: date | None, previous: date | None) -> bool:
    """判断 candidate 是否代表更早的可得申报；无日期不覆盖有日期记录。"""
    return _filing_sort_key(candidate) < _filing_sort_key(previous)


__all__ = [
    "CAPEX_XBRL_CONCEPTS",
    "OPERATING_CASH_FLOW_XBRL_CONCEPTS",
    "REVENUE_XBRL_CONCEPTS",
    "extract_sec_quarterly_capex",
    "extract_sec_quarterly_capex_with_filing_dates",
    "extract_sec_quarterly_metric_with_filing_dates",
]
