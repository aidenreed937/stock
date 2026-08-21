"""理杏仁特殊日期范围与响应字段辅助函数。"""

from datetime import date, timedelta
from typing import Any

_EXCLUSIVE_RANGE_ENDPOINTS = {
    "macro/national-debt",
    "macro/interest-rates",
    "macro/non-ferrous-metals",
    "macro/crude-oil",
}


def query_date_range(endpoint: str, start_date: date, end_date: date) -> tuple[date, date]:
    """扩展理杏仁开区间接口的查询边界。"""
    if endpoint in _EXCLUSIVE_RANGE_ENDPOINTS:
        return start_date - timedelta(days=1), end_date + timedelta(days=1)
    return start_date, end_date


def query_date_strings(endpoint: str, start_date: date, end_date: date) -> tuple[str, str]:
    """返回理杏仁接口需要的格式化日期范围。"""
    query_start, query_end = query_date_range(endpoint, start_date, end_date)
    return query_start.strftime("%Y-%m-%d"), query_end.strftime("%Y-%m-%d")


def ensure_pledge_date_column(endpoint: str, frame: Any) -> Any:
    """为无快照日期的响应补齐可空日期列。"""
    if (
        endpoint in {"cn/company/hot/ple", "cn/company/hot/elr"}
        and "last_data_date" not in frame.columns
    ):
        frame = frame.copy()
        frame["last_data_date"] = None
    return frame


def ensure_lixinger_stock_code(endpoint: str, frame: Any, stock_code: str) -> Any:
    """为不回传 stockCode 的公司事件响应补齐请求标的。"""
    if (
        not stock_code
        or frame.empty
        or endpoint
        not in {
            "cn/company/measures",
            "cn/company/inquiry",
        }
    ):
        return frame
    if "stockCode" not in frame.columns:
        frame = frame.copy()
        frame.insert(0, "stockCode", stock_code)
    else:
        frame["stockCode"] = frame["stockCode"].fillna(stock_code)
    return frame


def query_frame(
    client: Any,
    api_name: str,
    endpoint: str,
    query_kwargs: dict[str, Any],
    stock_code: str = "",
) -> Any:
    """执行理杏仁查询并补齐特殊响应字段。"""
    frame = client.query(api_name, **query_kwargs)
    if frame.empty:
        return frame
    frame = ensure_pledge_date_column(endpoint, frame)
    return ensure_lixinger_stock_code(endpoint, frame, stock_code)
