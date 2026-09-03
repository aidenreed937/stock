"""快速宏观截面脚本的周期收益计算测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import polars as pl
import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / ".agents/skills/macro-risk-research/scripts/extract_cycle_snapshot.py"
)
_calculate_period_return = run_path(str(_SCRIPT_PATH))["_calculate_period_return"]


@pytest.mark.parametrize(("days", "expected"), [(20, 20.0), (60, 60.0)])
def test_calculate_period_return_uses_n_trading_intervals(days: int, expected: float) -> None:
    closes = pl.Series("close", [float(100 + i) for i in range(days + 1)])

    assert _calculate_period_return(closes, days) == pytest.approx(expected)
