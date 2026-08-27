"""指标与特征统一物理/标准化单位枚举（全仓唯一事实源）。

历史：`stock_analytics.features.spec.FeatureUnit` 与
`stock_analytics.metrics.spec.MetricUnit` 曾各自定义一套成员完全相同的枚举，
靠 docstring 互相"对齐"维持一致。P4 将其收敛下沉至最底层 `stock_core`，
消除双枚举漂移风险；features/metrics 通过 `import-as` 别名继续暴露
`FeatureUnit` / `MetricUnit` 名字（消费方零改动）。成员与取值保持不变。
"""

from __future__ import annotations

from enum import StrEnum


class Unit(StrEnum):
    """指标/特征物理或标准化单位。

    取值同时服务于 :class:`stock_analytics.features.spec.FeatureSpec` 与
    :class:`stock_analytics.metrics.spec.MetricSpec`。
    """

    CNY = "CNY"  # 人民币金额（元/亿元）
    SHARES = "shares"  # 股数/份额
    COUNT = "count"  # 家数/次数
    RATIO = "ratio"  # 比例/比率（小数，如 0.03 表示 3%）
    PERCENT = "percent"  # 百分数（如 2.5 表示 2.5%）
    PERCENTILE = "percentile"  # 历史分位数 (0~100)
    ZSCORE = "zscore"  # 标准化 Z-Score (通常无界，均值0方差1)
    SCORE_0_100 = "score_0_100"  # 0~100 综合评分
    BOOLEAN = "boolean"  # 布尔值 (0/1 或 True/False)
    UNKNOWN = "unknown"  # 未指定/复合


__all__ = ["Unit"]
