"""增量同步结果状态策略。"""

from __future__ import annotations

_EXPECTED_EMPTY_TASKS = frozenset(
    {
        ("tushare", "fund_adj"),
        ("yfinance", "dividends"),
        ("yfinance", "splits"),
    }
)


def _allows_empty_result(data_source: str, endpoint: str) -> bool:
    return (data_source.lower(), endpoint.strip()) in _EXPECTED_EMPTY_TASKS


def empty_result_status(data_source: str, endpoint: str) -> str:
    """返回成功请求但无记录时的区分状态。"""
    return "NO_DATA_EXPECTED" if _allows_empty_result(data_source, endpoint) else "NO_DATA_SOURCE"


def empty_result_reason(data_source: str, endpoint: str) -> str:
    """返回成功请求但无记录时的可观测原因。"""
    if _allows_empty_result(data_source, endpoint):
        return "任务契约允许请求区间内无记录，例如该标的在区间内未发生对应事件"
    return (
        "上游请求已成功，但在请求区间内未返回记录；可能是统计期间尚未发布，或该标的没有对应业务数据"
    )
