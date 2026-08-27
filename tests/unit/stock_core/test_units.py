"""stock_core.units 单位枚举契约测试。"""

from __future__ import annotations

import stock_core.units as units_module
from stock_core.units import Unit


def test_unit_members_and_values() -> None:
    """锁定统一单位枚举的成员全集与取值（P4 收敛后的事实源）。"""
    assert [member.value for member in Unit] == [
        "CNY",
        "shares",
        "count",
        "ratio",
        "percent",
        "percentile",
        "zscore",
        "score_0_100",
        "boolean",
        "unknown",
    ]
    assert Unit.CNY is Unit("CNY")
    assert Unit.RATIO is Unit("ratio")


def test_unit_is_str_enum() -> None:
    """Unit 为 StrEnum，可直接与字符串比较并序列化。"""
    assert str(Unit.PERCENT) == "percent"
    assert Unit.PERCENT == "percent"
    assert Unit.PERCENT != "ratio"


def test_unit_docstring_notes_analytics_aliases() -> None:
    """文档说明 features/metrics 通过别名复用本枚举。"""
    doc = units_module.__doc__ or ""
    assert "FeatureUnit" in doc
    assert "MetricUnit" in doc
