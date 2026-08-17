"""市场宽度面板规则：个股收益率、均线站上、创新高新低与占比。

宽度规则作用于个股面板（含 symbol 列），滚动窗口按标的独立计算，
因此表达式中已内嵌 .over("symbol")。
"""

from stock.analytics.primitives.rules import (
    above_ma,
    at_rolling_high,
    at_rolling_low,
    daily_return,
    share,
)

__all__ = [
    "above_ma",
    "at_rolling_high",
    "at_rolling_low",
    "daily_return",
    "share",
]
