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


def effective_month(report_month: str) -> str:
    """信号生效月：report_month 数据发布后，下一个完整月才可交易。

    即 release_date 所在月的下一个月，返回 ``YYYY-MM``。消除回测中
    "用 M 月数据在 M 月建仓"的约 1 个月发布时滞前视（见 release_date_for）。
    """
    rd = release_date_for(report_month)
    if rd.month == 12:
        return f"{rd.year + 1:04d}-01"
    return f"{rd.year:04d}-{rd.month + 1:02d}"


__all__ = ["effective_month", "release_date_for"]
