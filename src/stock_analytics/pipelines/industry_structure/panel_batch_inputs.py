"""行业面板 Mart 共享实现兼容门面。"""

from importlib import import_module as _import_module

from stock_analytics.marts.shared.industry_structure.panel_batch_inputs import *  # noqa: F401,F403

_target = _import_module("stock_analytics.marts.shared.industry_structure.panel_batch_inputs")
__all__ = getattr(_target, "__all__", ())


def __getattr__(name: str) -> object:
    return getattr(_target, name)
