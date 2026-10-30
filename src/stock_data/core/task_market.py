"""任务归属市场解析。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stock_data.core.provider_registry import provider_registry

_DEFAULT_MARKETS = {
    "tushare": "CN",
    "yfinance": "US",
    "lixinger": "CN",
    "fred": "US",
    "alphavantage": "GLOBAL",
    "derived": "CN",
}


def default_market(provider: str, api_name: str) -> str:
    """返回指定数据源在缺少元数据时的市场默认值。"""
    provider_lower = provider.lower()
    if provider_lower == "lixinger" and api_name.startswith("hk"):
        return "HK"
    return _DEFAULT_MARKETS.get(provider_lower, "MULTI")


def market_for_api(provider: str, api_name: str) -> str:
    """根据上游 API 名称读取 Provider registry 中的市场归属。"""
    provider_lower = provider.lower()
    meta: Any | None = provider_registry(provider_lower).get(api_name)
    if meta is not None and hasattr(meta, "market"):
        return str(meta.market)
    return default_market(provider_lower, api_name)


def resolve_endpoint_market(
    provider: str,
    endpoint: str,
    resolve_api_name: Callable[[str, str], str] | None = None,
) -> str:
    """根据项目任务名或上游接口名解析市场归属。"""
    provider_lower = provider.lower()
    api_name = endpoint
    if resolve_api_name is not None:
        try:
            api_name = resolve_api_name(provider_lower, endpoint)
        except ValueError:
            pass
    return market_for_api(provider_lower, api_name)


__all__ = ["default_market", "market_for_api", "resolve_endpoint_market"]
