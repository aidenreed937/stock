"""TuShare 上游内部 API 名称保护。"""

from __future__ import annotations

TUSHARE_INTERNAL_PERIOD_TASKS: frozenset[str] = frozenset(
    {
        "income",
        "fina_indicator",
        "fina_mainbz",
        "balancesheet",
        "cashflow",
        # fund_portfolio 不在此列：它按基金代码查询（per_symbol），没有报告期批量语义，
        # 传 period 会被上游静默忽略并退化为前 8000 行切片（历史事故根因）。
        "top10_floatholders",
        "stk_holdernumber",
    }
)


def is_tushare_internal_api(name: str) -> bool:
    """判断名称是否为财务报表 VIP 内部接口。"""
    return name.endswith("_vip") and name.removesuffix("_vip") in TUSHARE_INTERNAL_PERIOD_TASKS


__all__ = ["TUSHARE_INTERNAL_PERIOD_TASKS", "is_tushare_internal_api"]
