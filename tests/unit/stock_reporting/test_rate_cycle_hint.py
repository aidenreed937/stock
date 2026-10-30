"""利率周期风险提示单元测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.macro_risk.fred import FedFundsSnapshot
from stock_reporting.interpretation.macro_risk.rate_cycle_hint import rate_cycle_hint
from stock_reporting.templates.macro_risk_report import render_macro_risk_report


def test_rate_cycle_hint_hike_phase_raw_pp() -> None:
    hint = rate_cycle_hint(0.69, 80.0)
    assert hint is not None
    assert hint["status"] == "加息周期中"
    assert hint["icon"] == "🔴"
    assert "胜率 32%" in hint["text"]
    assert "0.69" in hint["detail"]


def test_rate_cycle_hint_cut_phase() -> None:
    hint = rate_cycle_hint(-0.5, 30.0)
    assert hint["status"] == "降息周期中"
    assert hint["icon"] == "🟢"
    assert "胜率 73%" in hint["text"]


def test_rate_cycle_hint_plateau() -> None:
    hint = rate_cycle_hint(-0.01, 33.1)
    assert hint["status"] == "利率平台期"
    assert hint["icon"] == "🟡"
    assert "边际方向变化" in hint["text"]


def test_rate_cycle_hint_discloses_fred_observation_date() -> None:
    hint = rate_cycle_hint(-0.01, 33.1, date(2026, 9, 1))
    assert "FRED 截至 2026-09-01" in hint["detail"]


def test_rate_cycle_hint_score_only_fallback() -> None:
    """原始 pp 缺失时，score≥60 仍判定加息期。"""
    hint = rate_cycle_hint(None, 85.0)
    assert hint["status"] == "加息周期中"
    low = rate_cycle_hint(None, 33.0)
    assert low["status"] == "利率平台期"


def test_rate_cycle_hint_all_missing_returns_none() -> None:
    assert rate_cycle_hint(None, None) is None


def test_render_simple_includes_rate_cycle_hint() -> None:
    """简单版模板：ffr 原始值在黄金表有数据时渲染风险提示区块。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 9, 3)],
            "overheat_index": [55.0],
            "panic_index": [55.0],
            "dim_valuation": [44.4],
            "dim_leverage": [73.6],
            "dim_fear": [45.7],
            "dim_crowding": [65.6],
            "dim_breadth": [66.7],
            "dim_flow": [37.1],
            "ffr_chg_6m_score": [33.1],
        }
    )
    md = render_macro_risk_report(df, date(2026, 9, 3))
    assert "利率周期风险提示" in md
    assert "平台期" in md or "加息" in md or "降息" in md


def test_render_rate_cycle_hint_discloses_fred_observation_date(monkeypatch) -> None:
    import stock_reporting.templates.macro_risk_report as report_module

    monkeypatch.setattr(
        report_module,
        "_load_fred_rate_snapshot",
        lambda _target_date: FedFundsSnapshot(-0.01, date(2026, 9, 1), "fedfunds"),
    )
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 9, 30)],
            "overheat_index": [55.0],
            "panic_index": [55.0],
            "dim_valuation": [44.4],
            "dim_leverage": [73.6],
            "dim_fear": [45.7],
            "dim_crowding": [65.6],
            "dim_breadth": [66.7],
            "dim_flow": [37.1],
            "ffr_chg_6m_score": [33.1],
        }
    )
    md = render_macro_risk_report(df, date(2026, 9, 30))
    assert "FRED 截至 2026-09-01" in md


def test_render_pro_includes_rate_cycle_hint_section() -> None:
    """专业版模板：区块恒存在，数据缺失时显示数据暂缺。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 28)],
            "overheat_index": [69.2],
            "panic_index": [33.9],
            "dim_valuation": [47.2],
            "dim_leverage": [84.9],
            "dim_fear": [28.8],
            "dim_crowding": [78.4],
            "dim_breadth": [37.0],
            "dim_flow": [35.7],
        }
    )
    md = render_macro_risk_report(df, date(2026, 8, 28), template="pro")
    assert "利率周期风险提示" in md
    # 无 ffr 列时回退分位缺失 → 数据暂缺（黄金表原始值可能命中则显示状态）
    assert ("数据暂缺" in md) or ("平台期" in md) or ("加息" in md)
