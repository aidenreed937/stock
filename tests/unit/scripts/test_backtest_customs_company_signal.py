"""backtest_customs_company_signal.py 状态机权重计划单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "backtest_customs_company_signal.py"
)
_mod = run_path(str(_SCRIPT_PATH))
build_weight_plan = _mod["build_weight_plan"]


def test_enters_after_confirmed_positive_and_ramps_lots() -> None:
    # i=1,2 连续正（确认）→ 确认当月（i=2）起 1/3 建仓、逐月加仓
    vals = [None, 0.5, 0.4, 0.6, 0.3, 0.9, 0.8]
    w = build_weight_plan(vals, entry_confirm=2, exit_confirm=2)
    assert w[0] == 0.0 and w[1] == 0.0
    assert w[2] == pytest.approx(1 / 3) and w[3] == pytest.approx(2 / 3)
    assert w[4] == 1.0 and w[5] == 1.0


def test_clears_on_negative_yoy() -> None:
    vals = [0.5, 0.4, 0.6, -0.2, 0.3]
    w = build_weight_plan(vals, entry_confirm=1, exit_confirm=2)
    # i=0 确认即建 1/3，i=1 2/3，i=2 满仓，i=3 yoy<0 清仓，i=4 重新确认 1/3
    assert w[0] == pytest.approx(1 / 3)
    assert w[2] == 1.0
    assert w[3] == 0.0
    assert w[4] == pytest.approx(1 / 3)


def test_halves_on_confirm_peak_then_clears() -> None:
    # 满仓后 yoy 连续 2 月环比下降 → 减半；随后转负 → 清仓
    vals = [0.5, 0.6, 0.1, 0.05, -0.1]
    w = build_weight_plan(vals, entry_confirm=1, exit_confirm=2)
    assert w[0] == pytest.approx(1 / 3)
    assert w[1] == pytest.approx(2 / 3)
    assert w[2] == 1.0  # 0.6→0.1 首降，未达 2 月
    assert w[3] == 0.5  # 连续 2 月下降 → 减半
    assert w[4] == 0.0  # yoy<=0 清仓


def test_quality_gate_filters_price_driven_entry() -> None:
    vals = [0.5, 0.4, 0.6, 0.3]
    drives = ["价驱动", "价驱动", "量价齐升", "量驱动"]
    w_base = build_weight_plan(vals, entry_confirm=2, exit_confirm=2)
    w_qg = build_weight_plan(
        vals, entry_confirm=2, exit_confirm=2, drives=drives, quality_gate=True
    )
    # 基础版 2017 型：i=0,1 正即可确认，i=2 已 1/3
    assert w_base[2] > 0
    # 质量版：i=0,1 是价驱动不满足 → i=2,3 量价齐升/量驱动 确认 → 无建仓（序列太短未满 2 月？i=2,3 连续满足）
    assert w_qg[0] == 0.0 and w_qg[1] == 0.0
    assert w_qg[3] > 0  # i=2,3 连续质量正，i=3 起建仓 1/3
