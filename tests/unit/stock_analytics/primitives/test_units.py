"""统一金额单位换算测试。"""

from stock_analytics.primitives.units import YUAN_PER_YI, yuan_to_yi


def test_yuan_to_yi_preserves_unit_and_precision() -> None:
    assert YUAN_PER_YI == 100_000_000.0
    assert yuan_to_yi(56_346_000_000.0, precision=2) == 563.46
    assert yuan_to_yi(-8_910_000.0, precision=2) == -0.09
    assert yuan_to_yi(None) is None
