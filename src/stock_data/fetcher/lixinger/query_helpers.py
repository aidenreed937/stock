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
    """为无质押数据的响应补齐可空日期列。"""
    if endpoint == "cn/company/hot/ple" and "last_data_date" not in frame.columns:
        frame = frame.copy()
        frame["last_data_date"] = None
    return frame


def query_frame(client: Any, api_name: str, endpoint: str, query_kwargs: dict[str, Any]) -> Any:
    """执行理杏仁查询并补齐特殊响应字段。"""
    frame = client.query(api_name, **query_kwargs)
    if frame.empty:
        return frame
    return ensure_pledge_date_column(endpoint, frame)
