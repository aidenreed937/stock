"""分析层统一单位换算。"""

from __future__ import annotations

YUAN_PER_YI = 100_000_000.0


def yuan_to_yi(value: float | None, *, precision: int | None = None) -> float | None:
    """将以元计的金额转换为亿元。"""
    if value is None:
        return None
    converted = float(value) / YUAN_PER_YI
    return round(converted, precision) if precision is not None else converted


__all__ = ["YUAN_PER_YI", "yuan_to_yi"]
