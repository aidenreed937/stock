"""metrics 规则库：被计算器、物化层与消费方复用的纯表达式规则。

与绑定层（spec/registry/engine）正交：规则只定义"输入列 → 输出列"的
计算表达式，不关心指标元数据与数据集加载。
"""

from stock.analytics.metrics.rules.breadth import (
    above_ma,
    at_rolling_high,
    at_rolling_low,
    daily_return,
    share,
)
from stock.analytics.metrics.rules.rolling import (
    growth,
    percentile_rank,
    rolling_percentile,
    rolling_zscore,
)

__all__ = [
    "above_ma",
    "at_rolling_high",
    "at_rolling_low",
    "daily_return",
    "growth",
    "percentile_rank",
    "rolling_percentile",
    "rolling_zscore",
    "share",
]
