"""滚动统计规则：Z 分数、历史分位与增长率。

规则均为纯表达式构造函数，返回 polars Expr（分位规则同时提供
Series 级 percentile_rank 供单点取值场景复用）。分组粒度由调用方
通过 .over() 组合，本模块不隐含分组。
"""

from stock.analytics.primitives.rules import (
    growth,
    percentile_rank,
    rolling_percentile,
    rolling_zscore,
)

__all__ = [
    "growth",
    "percentile_rank",
    "rolling_percentile",
    "rolling_zscore",
]
