"""宏观风控解读逻辑与报告渲染单元测试。"""

from datetime import date

import polars as pl

from stock_reporting.interpretation.macro_risk.logic import evaluate_macro_risk
from stock_reporting.templates.macro_risk_report import render_macro_risk_report


def test_evaluate_macro_risk_dual_extremes() -> None:
    row = {
        "trade_date": date(2015, 6, 26),
        "overheat_index": 69.5,
        "panic_index": 70.9,
        "dim_leverage": 100.0,
        "dim_crowding": 95.9,
        "dim_valuation": 60.0,
        "dim_sentiment": 27.7,
        "dim_breadth": 95.0,
        "dim_flow": 90.2,
    }
    res = evaluate_macro_risk(row)
    assert "双极值共振" in res["status"]
    assert res["level"] == "danger"
    assert "严禁抄底" in res["status"]
    assert "杠杆多杀多" in res["advice"]


def test_evaluate_macro_risk_extreme_overheat() -> None:
    row = {
        "trade_date": date(2026, 8, 26),
        "overheat_index": 68.0,
        "panic_index": 40.0,
        "dim_leverage": 95.0,
        "dim_crowding": 70.0,
        "dim_valuation": 50.0,
        "dim_sentiment": 30.0,
    }
    res = evaluate_macro_risk(row)
    assert "极度狂热" in res["status"]
    assert res["level"] == "danger"


def test_evaluate_macro_risk_panic_volume_bottom() -> None:
    row = {
        "trade_date": date(2015, 8, 24),
        "overheat_index": 50.0,
        "panic_index": 92.0,
        "dim_crowding": 85.0,
        "dim_breadth": 99.0,
    }
    res = evaluate_macro_risk(row)
    assert "放量出清底" in res["status"]
    assert res["level"] == "opportunity"


def test_evaluate_macro_risk_panic_shrink_bottom() -> None:
    row = {
        "trade_date": date(2016, 1, 7),
        "overheat_index": 35.0,
        "panic_index": 87.0,
        "dim_crowding": 10.0,
        "dim_breadth": 98.0,
    }
    res = evaluate_macro_risk(row)
    assert "缩量绝望底" in res["status"]
    assert res["level"] == "opportunity"


def test_render_macro_risk_report_dual_extremes() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2015, 6, 26)],
            "overheat_index": [69.5],
            "panic_index": [70.9],
            "dim_valuation": [60.0],
            "dim_leverage": [100.0],
            "dim_sentiment": [27.7],
            "dim_crowding": [95.9],
            "dim_breadth": [95.0],
            "dim_flow": [90.2],
        }
    )
    md = render_macro_risk_report(df, date(2015, 6, 26))
    assert "宏观风控双轨制雷达日报" in md
    assert "双极值共振" in md
    assert "69.5" in md
    assert "70.9" in md


def test_evaluate_macro_risk_etf_support() -> None:
    row = {
        "trade_date": date(2025, 4, 7),
        "overheat_index": 45.0,
        "panic_index": 80.0,
        "dim_flow": 75.0,
        "etf_flow_ratio_score": 95.0,
        "dim_crowding": 60.0,
    }
    res = evaluate_macro_risk(row)
    flow_item = next(
        item for tier in res["risk_tiers"] for item in tier["metrics"] if item["code"] == "dim_flow"
    )
    assert flow_item["status"] == "国家队托底"
    assert "🟢" in flow_item["badge"]


def test_evaluate_macro_risk_divergence_distribution() -> None:
    row = {
        "trade_date": date(2021, 2, 18),
        "overheat_index": 68.0,
        "panic_index": 45.0,
        "dim_flow": 72.0,
        "divergence_score_score": 90.0,
    }
    res = evaluate_macro_risk(row)
    flow_item = next(
        item for tier in res["risk_tiers"] for item in tier["metrics"] if item["code"] == "dim_flow"
    )
    assert flow_item["status"] == "主力派发"
    assert "🔴" in flow_item["badge"]
