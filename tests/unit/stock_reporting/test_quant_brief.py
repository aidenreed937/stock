"""量化投研简报解读与渲染测试。"""

from datetime import date

import polars as pl

from stock_reporting.interpretation.quant_brief.config import load_quant_brief_config
from stock_reporting.interpretation.quant_brief.interpretation import (
    evaluate_macro,
    evaluate_nature,
    evaluate_veto,
)
from stock_reporting.templates.quant_brief import (
    build_quant_brief_json,
    render_quant_brief_markdown,
)


def test_macro_uses_configured_temperature_band_and_high_risk_override() -> None:
    config = load_quant_brief_config()
    scores = {
        "composite": {"temperature": 55.0},
        "systemic_risk": {
            "level": "高",
            "status": "high_systemic_risk",
            "message": "多项系统性风险信号同时进入高位。",
        },
    }

    result = evaluate_macro(config, scores)

    assert result["band_id"] == "high_risk"
    assert result["equity_position_band"] == "0%-30%"
    assert any("系统性风险" in reason for reason in result["reasons"])


def test_nature_requires_comparison_delta_for_true_bull_label() -> None:
    config = load_quant_brief_config()
    market_scores = {
        "composite": {"temperature": 65.0},
        "drivers": {"status": "insufficient"},
        "dimensions": [
            {"dimension_id": "technical", "temperature": 70.0},
            {"dimension_id": "fund_flow", "temperature": 65.0},
        ],
    }
    industry_scores = {
        "trend_diagnostics": {
            "positive_return_20d_count": 27,
            "positive_return_60d_count": 26,
            "scored_industry_count": 31,
        }
    }

    result = evaluate_nature(config, market_scores, industry_scores, None)

    assert result["nature_type"] != "true_bull_resonance"
    assert result["comparison_status"] == "insufficient_comparison"
    assert "不能仅凭当前截面确认" in result["message"]


def test_veto_keeps_top5_ratio_and_marks_margin_turning_point_insufficient() -> None:
    config = load_quant_brief_config()
    facts = _facts(
        [
            ("amount_top_5pct_share", 0.55),
            ("margin_balance_growth_20d", -0.01),
            ("margin_balance_growth_60d", 0.02),
        ]
    )
    panel = pl.DataFrame(
        [
            {
                "industry_name": "通信",
                "industry_code": "801760",
                "status": "ok",
                "structure_score": 72.0,
                "structure_rank": 1,
                "crowding_temperature": 85.0,
                "tcr": 4.2,
                "tags": "拥挤风险",
            }
        ]
    )
    industry_scores = {
        "structure_health": {"crowded_industry_share": 35.0},
    }

    result = evaluate_veto(config, {}, industry_scores, panel, facts)

    assert result["status"] == "triggered"
    assert result["top5pct"]["value"] == 0.55
    assert result["margin"]["turning_point_status"] == "insufficient_history"
    assert any(flag["id"] == "market_top5_concentration" for flag in result["flags"])
    assert any(flag["id"] == "margin_growth_negative" for flag in result["flags"])


def test_render_quant_brief_contains_four_decision_sections() -> None:
    config = load_quant_brief_config()
    market_scores = {
        "composite": {"temperature": 45.0},
        "systemic_risk": {"level": "中等", "status": "moderate_systemic_risk"},
        "drivers": {"status": "no_comparison"},
        "dimensions": [
            {"dimension_id": "technical", "temperature": 55.0},
            {"dimension_id": "fund_flow", "temperature": 48.0},
            {"dimension_id": "valuation", "temperature": 60.0},
            {"dimension_id": "sentiment", "temperature": 50.0},
        ],
    }
    industry_scores = {
        "structure_health": {
            "crowded_industry_share": 20.0,
            "positive_return_20d_count": 15,
            "positive_return_60d_count": 8,
            "scored_industry_count": 31,
        },
        "trend_diagnostics": {},
    }
    facts = _facts([("amount_top_5pct_share", 0.32)])
    panel = pl.DataFrame(
        [
            {
                "industry_name": "煤炭",
                "industry_code": "801950",
                "status": "ok",
                "structure_score": 72.0,
                "structure_rank": 1,
                "momentum_score": 80.0,
                "valuation_score": 75.0,
                "fundamental_score": 65.0,
                "fund_flow_score": 80.0,
                "return_20d": 0.1,
                "return_60d": 0.2,
                "crowding_temperature": 40.0,
                "tcr": 3.0,
                "tags": "资金确认",
            }
        ]
    )
    manifest = {
        "as_of_date": "2026-08-14",
        "inputs": {
            "market_temperature": {"run_id": "run_market"},
            "industry_structure": {"run_id": "run_industry"},
        },
    }

    brief = build_quant_brief_json(
        config=config,
        manifest=manifest,
        market_scores=market_scores,
        industry_scores=industry_scores,
        industry_panel=panel,
        market_facts=facts,
    )
    markdown = render_quant_brief_markdown(brief)

    assert "## 1. 宏观定基调" in markdown
    assert "## 2. 量价判性质" in markdown
    assert "## 3. 微观排雷与一票否决" in markdown
    assert "## 4. 中观选方向" in markdown
    assert brief["veto"]["top5pct"]["value"] == 0.32


def _facts(values: list[tuple[str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "category": ["metric_value"] * len(values),
            "dimension": ["sentiment", "fund_flow", "fund_flow"][: len(values)],
            "metric_id": [item[0] for item in values],
            "value_float": [item[1] for item in values],
            "metric_date": [date(2026, 8, 14)] * len(values),
            "as_of_date": [date(2026, 8, 14)] * len(values),
            "status": ["ok"] * len(values),
            "sample_size": [31] * len(values),
        }
    )
