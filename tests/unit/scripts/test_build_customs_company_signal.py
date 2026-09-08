"""build_customs_company_signal.py（三层信号合成）信号判定单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "build_customs_company_signal.py"
_mod = run_path(str(_SCRIPT_PATH))
export_leg_state = _mod["export_leg_state"]
fund_leg_state = _mod["fund_leg_state"]
fin_leg_state = _mod["fin_leg_state"]
rate = _mod["rate"]


def test_export_leg_state_grades_strength() -> None:
    assert export_leg_state(0.5, "量价齐升", None, None)[0] == "强正"
    assert export_leg_state(0.2, "价驱动", None, None)[0] == "正"
    assert export_leg_state(-0.05, "双弱", None, None)[0] == "弱"
    assert export_leg_state(-0.3, "双弱", None, None)[0] == "负"
    assert export_leg_state(None, None, None, None)[0] == "未知"


def test_export_leg_state_marks_turning_points() -> None:
    _, ev = export_leg_state(0.2, "量价齐升", "启动拐点", None)
    assert "启动" in ev
    _, ev2 = export_leg_state(-0.1, "双弱", "见顶拐点", "量增速回落")
    assert "见顶/回落" in ev2


def test_fund_leg_state_combines_main_and_margin() -> None:
    # 主力或两融任一确认即正
    assert fund_leg_state(1.0, None)[0] == "正"
    assert fund_leg_state(0.0, 3.0)[0] == "正"
    # 双负才负
    assert fund_leg_state(-1.0, -3.0)[0] == "负"
    # 混合/中性
    assert fund_leg_state(-1.0, 1.0)[0] == "平"
    assert fund_leg_state(None, None)[0] == "未知"


def test_fin_leg_state_grades_expansion() -> None:
    assert fin_leg_state(20.0, 15.0)[0] == "真扩张"
    assert fin_leg_state(20.0, -5.0)[0] == "增收不增利"
    assert fin_leg_state(-5.0, -10.0)[0] == "未兑现"
    assert fin_leg_state(None, 10.0)[0] == "未知"


def test_rate_three_leg_resonance() -> None:
    # A：出口强正 + 资金正 + 财报真扩张
    assert rate("强正", "正", "真扩张", None, None)[0] == "A强机会"
    # B：出口正 + 资金正（财报未确认）
    assert rate("正", "正", "未知", None, None)[0] == "B确认中"
    # C：出口正 + 财报真扩张（资金未跟）
    assert rate("正", "平", "真扩张", None, None)[0] == "C兑现中"
    # D：仅出口正
    assert rate("正", "负", "未兑现", None, None)[0] == "D前瞻观察"
    # 顶背离：出口见顶/回落 + 资金负 + 财报仍正
    r, flag = rate("正", "负", "真扩张", "见顶拐点", None)
    assert r == "回避" and flag == "顶背离⚠"
    r2, _ = rate("负", "负", "真扩张", None, "量增速回落")
    assert r2 == "回避"
    # 观望
    assert rate("负", "负", "未兑现", None, None)[0] == "观望"
