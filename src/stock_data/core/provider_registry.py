"""Provider 原生 API 注册表的延迟加载入口。"""

from __future__ import annotations

from typing import Any

PROVIDER_REGISTRY_IMPORTS: dict[str, tuple[str, str]] = {
    "tushare": ("stock_data.fetcher.tushare.registry", "TUSHARE_API_REGISTRY"),
    "yfinance": ("stock_data.fetcher.yfinance.registry", "YFINANCE_API_REGISTRY"),
    "lixinger": ("stock_data.fetcher.lixinger.registry", "LIXINGER_API_REGISTRY"),
    "fred": ("stock_data.fetcher.fred.registry", "FRED_API_REGISTRY"),
    "alphavantage": ("stock_data.fetcher.alphavantage.registry", "ALPHAVANTAGE_API_REGISTRY"),
}


def provider_registry(provider: str) -> dict[str, Any]:
    """按需加载 Provider 注册表，避免任务模块与各 Fetcher 形成循环依赖。"""
    module_path, registry_name = PROVIDER_REGISTRY_IMPORTS.get(provider.lower(), ("", ""))
    if not module_path:
        return {}
    module = __import__(module_path, fromlist=[registry_name])
    return getattr(module, registry_name)  # type: ignore[no-any-return]


__all__ = ["PROVIDER_REGISTRY_IMPORTS", "provider_registry"]
