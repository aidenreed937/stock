"""市场温度共享事实兼容门面。"""

from importlib import import_module as _import_module

from stock_analytics.marts.shared.market_temperature.derived_fundamental import *  # noqa: F401,F403

_target = _import_module("stock_analytics.marts.shared.market_temperature.derived_fundamental")
__all__ = getattr(_target, "__all__", ())


def __getattr__(name: str) -> object:
    return getattr(_target, name)
