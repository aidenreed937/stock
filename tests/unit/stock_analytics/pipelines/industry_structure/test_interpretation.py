"""行业结构研判与解读模块单元测试。"""

from __future__ import annotations

import polars as pl

from stock_reporting.interpretation.industry_structure.interpretation import (
    evaluate_breadth_comment,
    evaluate_one_line_summary,
    evaluate_structure_radar,
    get_fundamental_status_interpretation,
    get_fundamental_status_label,
    get_structure_health_level,
    has_fund_flow_pressure,
    has_weak_fundamental,
    is_fund_flow_confirmed,
    is_high_dividend,
)


def test_fundamental_status_label_and_interpretation() -> None:
    assert "财报未滞后" in get_fundamental_status_label("fresh_blended")
    assert "基本面数据不足" in get_fundamental_status_label("insufficient")

    interp = get_fundamental_status_interpretation({"stale_blended": 5})
    assert "正式行业财报更新偏慢" in interp


def test_evaluate_breadth_comment() -> None:
    assert "短线扩散较强" in evaluate_breadth_comment(20, 5, 31)
    assert "全面修复" in evaluate_breadth_comment(5, 5, 31)
    assert "同步改善" in evaluate_breadth_comment(25, 20, 31)


def test_structure_health_level() -> None:
    assert get_structure_health_level({"structure_health": {"level": "健康扩散"}}) == "健康扩散"
    assert get_structure_health_level({}) == "不可判定"


def test_predicates() -> None:
    row_weak_fund = {"fundamental_score": 30.0}
    assert has_weak_fundamental(row_weak_fund)

    row_fund_flow = {"fund_flow_score": 75.0, "money_net_inflow_share_20d": 0.05}
    assert is_fund_flow_confirmed(row_fund_flow)

    row_fund_pressure = {"fund_flow_score": 25.0, "money_net_inflow_share_20d": -0.05}
    assert has_fund_flow_pressure(row_fund_pressure)

    row_div = {"dividend_yield": 0.04}
    assert is_high_dividend(row_div)


def test_evaluate_one_line_summary() -> None:
    scores = {
        "top_structure": [{"industry_name": "银行"}, {"industry_name": "煤炭"}],
        "crowded_risk": [{"industry_name": "电子"}],
        "lagging_or_weak": [{"industry_name": "计算机"}],
    }
    summary = evaluate_one_line_summary(scores)
    assert "银行、煤炭" in summary
    assert "电子" in summary
    assert "计算机" in summary


def test_evaluate_structure_radar() -> None:
    df = pl.DataFrame(
        {
            "industry_name": ["银行", "电子"],
            "return_60d": [5.0, -2.0],
            "tcr": [3.0, 15.0],
            "fund_flow_score": [80.0, 40.0],
            "money_net_inflow_share_20d": [0.05, -0.02],
            "structure_score": [85.0, 60.0],
            "fundamental_score": [70.0, 30.0],
        }
    )
    scores = {"crowded_risk": [{"industry_name": "电子", "return_20d": 8.0, "tcr": 15.0}]}
    lines = evaluate_structure_radar(df, scores)
    assert any("60日正收益行业" in line for line in lines)
    assert any("成交集中 Top" in line for line in lines)
