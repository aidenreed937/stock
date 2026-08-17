"""市场温度研判与解读模块单元测试。"""

from __future__ import annotations

import polars as pl

from stock.analytics.pipelines.market_temperature.interpretation import (
    evaluate_external_pressure_section,
    evaluate_key_divergences,
    evaluate_one_line_summary,
    evaluate_reading_brief,
    evaluate_systemic_risk_section,
    get_cross_period_comment,
    get_dimension_comment,
    get_pressure_band,
    get_pressure_comment,
    get_temperature_band,
)


def test_temperature_and_pressure_bands() -> None:
    assert get_temperature_band(15.0) == "低温机会区"
    assert get_temperature_band(35.0) == "偏冷修复观察区"
    assert get_temperature_band(50.0) == "中性轮动区"
    assert get_temperature_band(70.0) == "偏热修复区"
    assert get_temperature_band(85.0) == "高温拥挤区"
    assert get_temperature_band(None) == "不可判定"

    assert get_pressure_band(85.0) == "高压力"
    assert get_pressure_band(65.0) == "中等偏高"
    assert get_pressure_band(45.0) == "中性"
    assert get_pressure_band(25.0) == "压力不明显"
    assert get_pressure_band(None) == "不可判定"


def test_pressure_comment() -> None:
    comment = get_pressure_comment("macro_external_pressure_temperature", 85.0)
    assert "压力高" in comment
    comment_none = get_pressure_comment("macro_external_pressure_temperature", None)
    assert "样本不足" in comment_none


def test_dimension_comment() -> None:
    comment = get_dimension_comment("valuation", 85.0)
    assert "估值" in comment
    assert "高温" in comment


def test_cross_period_comment() -> None:
    assert "总分接近" in get_cross_period_comment("综合温度", 2.0, "fallback")
    assert "明显升温" in get_cross_period_comment("情绪", 25.0, "fallback")
    assert "降温" in get_cross_period_comment("情绪", -10.0, "fallback")


def test_evaluate_one_line_summary() -> None:
    dims = [
        {"dimension_id": "valuation", "name": "估值", "temperature": 85.0},
        {"dimension_id": "sentiment", "name": "情绪", "temperature": 25.0},
    ]
    summary = evaluate_one_line_summary(dims, 55.0)
    assert "中性轮动区" in summary
    assert "估值(85.00)" in summary
    assert "情绪(25.00)" in summary


def test_evaluate_reading_brief() -> None:
    dims = [
        {"dimension_id": "valuation", "name": "估值", "temperature": 85.0},
        {"dimension_id": "technical", "name": "技术", "temperature": 35.0},
        {"dimension_id": "fund_flow", "name": "资金", "temperature": 75.0},
    ]
    scores = {"composite": {"temperature": 60.0}, "systemic_risk": {"level": "低风险"}}
    facts = pl.DataFrame(
        {
            "category": ["metric_value"],
            "metric_id": ["investor_account_temperature"],
            "value_float": [85.0],
            "status": ["ok"],
        }
    )
    brief = evaluate_reading_brief(dims, scores, facts)
    assert any("先定市场环境" in line for line in brief)
    assert any("高温来源" in line for line in brief)


def test_evaluate_systemic_risk_section() -> None:
    scores = {
        "systemic_risk": {
            "level": "中等风险",
            "message": "需关注流动性",
            "red_flags": ["杠杆过高"],
            "warnings": ["成交放量"],
            "offsets": ["低估值对冲"],
        }
    }
    lines = evaluate_systemic_risk_section(scores)
    assert any("中等风险" in line for line in lines)
    assert any("杠杆过高" in line for line in lines)


def test_evaluate_key_divergences() -> None:
    dims = [
        {"dimension_id": "technical", "name": "技术", "temperature": 65.0},
        {"dimension_id": "fund_flow", "name": "资金", "temperature": 40.0},
    ]
    facts = pl.DataFrame(
        {
            "category": ["metric_value"],
            "metric_id": ["margin_balance_growth_20d"],
            "value_float": [-0.05],
            "status": ["ok"],
        }
    )
    lines = evaluate_key_divergences(dims, facts)
    assert any("价格修复的资金确认不足" in line for line in lines)


def test_evaluate_external_pressure_section() -> None:
    facts = pl.DataFrame(
        {
            "category": ["metric_value", "metric_value"],
            "metric_id": [
                "macro_external_pressure_temperature",
                "macro_safe_haven_pressure_temperature",
            ],
            "value_float": [85.0, 70.0],
            "status": ["ok", "ok"],
        }
    )
    lines = evaluate_external_pressure_section(facts)
    assert any("总体外部压力" in line for line in lines)
    assert any("高压力" in line for line in lines)
