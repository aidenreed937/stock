"""投资者简报研判与决策模块单元测试。"""

from __future__ import annotations

import polars as pl

from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_candidate_industries,
    evaluate_lagging_industries,
    evaluate_participation_decision,
    evaluate_reading_notes,
    evaluate_risk_industries,
)


def test_evaluate_participation_decision_safe() -> None:
    market_scores = {
        "composite": {"temperature": 45.0},
        "systemic_risk": {"status": "contained_systemic_risk", "level": "低风险"},
    }
    industry_scores = {"structure_health": {"status": "healthy_diffusion"}}
    dimensions = {"valuation": 40.0, "fund_flow": 60.0, "technical": 50.0}

    decision = evaluate_participation_decision(market_scores, industry_scores, dimensions)
    assert "系统风险暂可控" in decision["stance"]
    assert decision["risk_level"] == "低风险"


def test_evaluate_participation_decision_high_risk() -> None:
    market_scores = {
        "composite": {"temperature": 85.0},
        "systemic_risk": {"status": "high_systemic_risk", "level": "高风险"},
    }
    industry_scores = {"structure_health": {}}
    dimensions = {"valuation": 85.0, "fund_flow": 40.0, "technical": 70.0}

    decision = evaluate_participation_decision(market_scores, industry_scores, dimensions)
    assert "以防守和等待为主" in decision["stance"]
    assert any("估值已经偏热" in r for r in decision["reasons"])


def test_evaluate_participation_decision_surfaces_external_shock_boundary() -> None:
    market_scores = {
        "composite": {"temperature": 60.0},
        "systemic_risk": {"status": "contained_systemic_risk", "level": "中等"},
        "external_risk": {"shock_status": "short_term_shock"},
    }

    decision = evaluate_participation_decision(
        market_scores,
        {"structure_health": {}},
        {"valuation": 50.0, "fund_flow": 55.0, "technical": 55.0},
    )

    assert any("外盘短线风险已出现" in reason for reason in decision["reasons"])


def test_evaluate_candidate_and_risk_industries() -> None:
    panel = pl.DataFrame(
        {
            "industry_name": ["银行", "电子", "房地产"],
            "status": ["ok", "ok", "ok"],
            "structure_score": [85.0, 75.0, 30.0],
            "structure_rank": [1, 2, 31],
            "return_20d": [4.0, 6.0, -5.0],
            "return_60d": [8.0, -2.0, -10.0],
            "crowding_temperature": [50.0, 85.0, 30.0],
            "valuation_score": [80.0, 30.0, 50.0],
            "fundamental_score": [70.0, 40.0, 20.0],
            "momentum_score": [60.0, 85.0, 20.0],
            "tcr": [3.0, 15.0, 2.0],
            "tags": ["", "拥挤风险", "景气承压"],
        }
    )
    candidates = evaluate_candidate_industries(panel, limit=3)
    assert len(candidates) == 1
    assert candidates[0]["industry_name"] == "银行"

    risks = evaluate_risk_industries(panel, limit=3)
    assert len(risks) == 1
    assert risks[0]["industry_name"] == "电子"

    lagging = evaluate_lagging_industries(panel, limit=3)
    assert len(lagging) >= 1
    assert lagging[0]["industry_name"] == "房地产"


def test_evaluate_reading_notes() -> None:
    market_scores = {"systemic_risk": {"message": "整体流动性稳健"}}
    industry_scores = {
        "structure_health": {
            "positive_return_20d_count": 20,
            "positive_return_60d_count": 15,
            "scored_industry_count": 31,
        }
    }
    notes = evaluate_reading_notes(market_scores, industry_scores)
    assert any("第一步只看系统风险" in n for n in notes)
    assert any("20/31" in n for n in notes)
