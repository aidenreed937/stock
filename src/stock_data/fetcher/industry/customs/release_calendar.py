"""海关统计数据公布时间表（确定性规则）。

GACC 数据源为 ``stats.customs.gov.cn``（海关统计在线查询平台），对应海关总署年度
《中国海关统计数据公布时间表》中的"在线查询数据"一列，其发布时间多年稳定为每月
20 日；1-2 月因春节合并，3 月 20 日发布；12 月数据次年 1 月 20 日发布。

2026 年依据海关总署公告 2025 年第 240 号核实；历史年份沿用同一规则外推
（在线查询列每年均为 20 日，见公告注一、注七）。
"""

from __future__ import annotations

from datetime import date


def release_date_for(report_month: str) -> date:
    """返回 report_month（``YYYY-MM``）在线查询数据的首次发布时间。

    规则：
    - 1 月、2 月 → 当年 3 月 20 日（1-2 月合并公布）；
    - 12 月 → 次年 1 月 20 日；
    - 其余月（3~11 月）→ 次月 20 日。
    """
    year = int(report_month[:4])
    month = int(report_month[5:7])
    if month in (1, 2):
        return date(year, 3, 20)
    if month == 12:
        return date(year + 1, 1, 20)
    return date(year, month + 1, 20)


__all__ = ["release_date_for"]
