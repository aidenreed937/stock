"""投资假设跨周期复盘单元测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_analytics.pipelines.stock_diagnostics.types import (
    CapitalFlowSnapshot,
    FinancialsSnapshot,
    MarketContextSnapshot,
    ScreenSnapshot,
    StockDiagnosticsResult,
    TechnicalsSnapshot,
    ValuationSnapshot,
)
from stock_analytics.pipelines.thesis_review import (
    InvestmentThesis,
    ThesisReviewAttribution,
    ThesisReviewResult,
    load_or_create_thesis,
    run_thesis_review,
)


def test_thesis_review_result_serialization() -> None:
    thesis = InvestmentThesis(
        thesis_id="600519_2026-05-20",
        symbol="600519.SH",
        name="贵州茅台",
        created_date="2026-05-20",
        base_price=1550.0,
        initial_pe_ttm=24.5,
        expected_growth=12.0,
        expected_pe_anchor=25.0,
    )
    attribution = ThesisReviewAttribution(
        current_price=1272.83,
        price_change_pct=-17.88,
        actual_growth=8.5,
        growth_gap=-3.5,
        current_pe_ttm=19.5,
        pe_change_pct=-20.4,
        is_stop_loss_triggered=True,
        is_value_trap=True,
        verdict="🚨 触及严格止损线 (建议执行风控纪律)",
        reflection_notes=["估值端收缩 20.4%"],
        action_guidance=["严格执行止损纪律"],
    )
    res = ThesisReviewResult(
        thesis=thesis,
        as_of_date="2026-08-21",
        days_elapsed=93,
        attribution=attribution,
    )

    d = res.to_dict()
    assert d["thesis"]["symbol"] == "600519.SH"
    assert d["attribution"]["price_change_pct"] == -17.88
    assert d["attribution"]["is_stop_loss_triggered"] is True


def test_load_or_create_thesis_from_yaml(tmp_path: Path) -> None:
    yaml_content = """
thesis_id: "600519_test"
symbol: "600519.SH"
name: "贵州茅台"
created_date: "2026-05-20"
base_price: 1550.0
initial_pe_ttm: 24.5
investment_thesis:
  expected_net_profit_growth: 12.0
  expected_pe_anchor: 25.0
risk_controls:
  max_drawdown_stop_loss: -15.0
"""
    p = tmp_path / "600519.SH_2026-05-20.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    t = load_or_create_thesis("600519.SH", theses_dir=tmp_path)
    assert t.symbol == "600519.SH"
    assert t.base_price == 1550.0
    assert t.expected_growth == 12.0


def test_run_thesis_review_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_diag = StockDiagnosticsResult(
        symbol="600519.SH",
        name="贵州茅台",
        as_of_date="2026-08-21",
        industry="白酒",
        area="贵州",
        market="主板",
        technicals=TechnicalsSnapshot(close=1272.83, pct_chg=-1.45, trend_description="震荡整理"),
        valuation=ValuationSnapshot(
            pe_ttm=19.5,
            pe_percentile_5y=4.7,
            pb=6.33,
            dv_ttm=4.09,
            dividend_spread_10y=2.41,
            value_trap_warning=True,
        ),
        financials=FinancialsSnapshot(netprofit_yoy=8.5, roe=17.95),
        capital_flow=CapitalFlowSnapshot(),
        screen=ScreenSnapshot(status="passed"),
        market_context=MarketContextSnapshot(),
    )

    from stock_analytics.pipelines.thesis_review import pipeline

    dummy_thesis = InvestmentThesis(
        thesis_id="600519_2026-05-20",
        symbol="600519.SH",
        name="贵州茅台",
        created_date="2026-05-20",
        base_price=1550.0,
        initial_pe_ttm=24.5,
        expected_growth=12.0,
        expected_pe_anchor=25.0,
    )

    monkeypatch.setattr(pipeline, "load_or_create_thesis", MagicMock(return_value=dummy_thesis))
    monkeypatch.setattr(pipeline, "run_stock_diagnostics", MagicMock(return_value=dummy_diag))

    res = run_thesis_review(
        symbol="600519.SH",
        thesis_date=date(2026, 5, 20),
        target_date=date(2026, 8, 21),
    )

    assert res.thesis.symbol == "600519.SH"
    assert res.attribution.price_change_pct < -15.0
    assert res.attribution.is_stop_loss_triggered is True
    assert res.attribution.is_value_trap is True
    assert "🚨" in res.attribution.verdict
