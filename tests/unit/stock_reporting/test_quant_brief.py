"""量化投研简报解读与渲染测试。"""

from datetime import date
from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import load_quant_brief_config
from stock_reporting.interpretation.quant_brief.interpretation import (
    evaluate_macro,
    evaluate_nature,
    evaluate_risk_gates,
    evaluate_sector,
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


def test_veto_marks_margin_turning_point_persistent_negative_with_series() -> None:
    config = load_quant_brief_config()
    facts = _facts(
        [
            ("margin_balance_growth_20d", -0.01),
            ("margin_balance_growth_60d", -0.02),
        ]
    )
    series = _margin_series([1.0 - idx * 0.005 for idx in range(25)])

    result = evaluate_veto(
        config,
        {},
        {},
        pl.DataFrame(),
        facts,
        margin_series=series,
    )

    margin = result["margin"]
    assert margin["turning_point_status"] == "persistent_negative"
    assert margin["turning_point"]["negative_days_5d"] == 5
    assert margin["turning_point"]["consecutive_negative_days"] == 5


def test_veto_marks_margin_turning_point_confirmed_up_with_series() -> None:
    config = load_quant_brief_config()
    facts = _facts(
        [
            ("margin_balance_growth_20d", -0.01),
            ("margin_balance_growth_60d", -0.02),
        ]
    )
    series = _margin_series([0.9] * 20 + [0.91, 0.92, 0.93, 0.94, 0.95, 0.96])

    result = evaluate_veto(
        config,
        {},
        {},
        pl.DataFrame(),
        facts,
        margin_series=series,
    )

    margin = result["margin"]
    assert margin["turning_point_status"] == "confirmed_turning"
    assert margin["turning_point"]["consecutive_positive_days"] >= 3


def _margin_series(values: list[float]) -> pl.DataFrame:
    from datetime import date as _date
    from datetime import timedelta

    start = _date(2026, 7, 1)
    return pl.DataFrame(
        {
            "trade_date": [start + timedelta(days=idx) for idx in range(len(values))],
            "margin_balance": values,
        }
    )


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
    assert "## 0. 风控闸门总览" in markdown
    assert "## 2. 量价判性质" in markdown
    assert "## 3. 微观排雷与一票否决" in markdown
    assert "## 4. 中观选方向" in markdown
    assert "主力资金与杠杆健康度" in markdown
    assert brief["veto"]["top5pct"]["value"] == 0.32
    assert "结构领先但未进入优先方向" in markdown


def test_quant_brief_exposes_effective_position_band_and_conservative_nature_label() -> None:
    config = load_quant_brief_config()
    brief = build_quant_brief_json(
        config=config,
        manifest={
            "as_of_date": "2026-08-14",
            "generated_at": "2026-08-14T18:00:00",
            "inputs": {
                "market_temperature": {"run_id": "run_market"},
                "industry_structure": {"run_id": "run_industry"},
            },
        },
        market_scores={
            "composite": {"temperature": 45.0},
            "systemic_risk": {"level": "低", "status": "normal"},
            "drivers": {"status": "no_comparison"},
            "dimensions": [
                {"dimension_id": "technical", "temperature": 55.0},
                {"dimension_id": "fund_flow", "temperature": 40.0},
                {"dimension_id": "valuation", "temperature": 55.0},
                {"dimension_id": "sentiment", "temperature": 50.0},
            ],
        },
        industry_scores={
            "structure_health": {
                "positive_return_20d_count": 15,
                "positive_return_60d_count": 8,
                "scored_industry_count": 31,
            },
            "trend_diagnostics": {},
        },
        industry_panel=_clear_panel(),
        market_facts=_facts(
            [
                ("main_large_order_net_inflow_share", -0.06),
                ("market_amount_percentile_1250d", 95.0),
            ]
        ),
    )

    assert brief["position_policy"]["temperature_band"] == "40%-50%"
    assert brief["position_policy"]["risk_cap"] == "0%-30%"
    assert brief["position_policy"]["effective_band"] == "0%-30%"
    assert brief["nature"]["nature_type"] == "distribution_risk"
    assert brief["nature"]["nature_label"] == "资金-成交背离风险（硬闸门观察）"
    legacy_brief = dict(brief)
    legacy_brief.pop("position_policy")
    assert "当前有效仓位: 0%-30%" in render_quant_brief_markdown(legacy_brief)


def test_sector_explains_structure_leaders_filtered_by_fund_flow() -> None:
    config = load_quant_brief_config()
    result = evaluate_sector(
        config,
        pl.DataFrame(
            [
                {
                    "industry_name": "煤炭",
                    "industry_code": "801950",
                    "status": "ok",
                    "structure_score": 80.0,
                    "structure_rank": 1,
                    "fund_flow_score": 95.0,
                    "money_net_inflow_share_20d": -0.01,
                    "return_20d": 0.1,
                    "return_60d": 0.2,
                    "crowding_temperature": 40.0,
                    "tcr": 3.0,
                    "tags": "低估改善、相对占优",
                },
                {
                    "industry_name": "银行",
                    "industry_code": "801780",
                    "status": "ok",
                    "structure_score": 60.0,
                    "structure_rank": 6,
                    "fund_flow_score": 80.0,
                    "money_net_inflow_share_20d": 0.02,
                    "return_20d": 0.05,
                    "return_60d": 0.08,
                    "crowding_temperature": 40.0,
                    "tcr": 3.0,
                    "tags": "资金确认、相对占优",
                },
            ]
        ),
    )

    assert [row["industry_name"] for row in result["priority"]] == ["银行"]
    assert [row["industry_name"] for row in result["priority_excluded"]] == ["煤炭"]
    assert "资金未确认" in result["priority_excluded"][0]["reason"]


def test_systemic_valuation_red_flag_sets_defensive_position_cap() -> None:
    config = load_quant_brief_config()
    result = evaluate_macro(
        config,
        {
            "composite": {"temperature": 45.0},
            "dimensions": [{"dimension_id": "valuation", "temperature": 85.0}],
            "systemic_risk": {"level": "中等", "status": "moderate_systemic_risk"},
        },
    )

    assert result["equity_position_band"] == "0%-30%"
    assert "防守" in result["stance"]
    assert "降低总仓位上限" in result["tactic"]


def test_composite_red_flag_is_reduce_only_without_hard_stop() -> None:
    config = load_quant_brief_config()
    result = evaluate_macro(
        config,
        {
            "composite": {"temperature": 65.0},
            "dimensions": [{"dimension_id": "valuation", "temperature": 60.0}],
            "systemic_risk": {"level": "低", "status": "normal"},
        },
    )

    assert "只减不加" in result["stance"]
    assert result["equity_position_band"] != "0%-30%"
    assert result["risk_gate"]["severity"] == "watch"


def test_funding_gate_requires_large_outflow_and_high_turnover_for_hard_stop() -> None:
    config = load_quant_brief_config()
    facts = _facts(
        [
            ("main_large_order_net_inflow_share", -0.06),
            ("main_money_net_inflow_share_20d_cum", -0.02),
            ("market_amount_percentile_1250d", 95.0),
            ("margin_buy_share", 0.11),
            ("margin_balance_growth_20d", -0.01),
            ("margin_balance_growth_60d", 0.01),
            ("margin_penetration_percentile_1250d", 96.0),
        ]
    )
    result = evaluate_risk_gates(
        config,
        {},
        {"structure_health": {"positive_return_20d_count": 15, "scored_industry_count": 31}},
        _clear_panel(),
        facts,
    )

    funding = _gate(result, "funding_leverage")
    assert funding["status"] == "triggered"
    assert funding["severity"] == "hard"
    assert result["hard_stop"] is True
    assert result["max_position_band"] == "0%-30%"


def test_funding_fallback_is_observation_not_level_two_hard_stop() -> None:
    config = load_quant_brief_config()
    facts = _facts(
        [
            ("main_money_net_inflow_share", -0.06),
            ("main_money_net_inflow_share_20d_cum", -0.02),
            ("market_amount_percentile_1250d", 95.0),
            ("margin_buy_share", 0.08),
            ("margin_balance_growth_20d", 0.01),
            ("margin_penetration_percentile_1250d", 80.0),
        ]
    )
    result = evaluate_risk_gates(config, {}, {}, _clear_panel(), facts)

    funding = _gate(result, "funding_leverage")
    assert funding["status"] == "watch"
    assert funding["severity"] == "watch"
    assert result["hard_stop"] is False


def test_breadth_gate_marks_weak_width_as_watch() -> None:
    config = load_quant_brief_config()
    facts = _facts([("above_ma60_share", 0.25)])
    result = evaluate_risk_gates(
        config,
        {"dimensions": [{"dimension_id": "technical", "temperature": 55.0}]},
        {"trend_diagnostics": {"positive_return_20d_count": 9, "scored_industry_count": 31}},
        _clear_panel(),
        facts,
    )

    breadth = _gate(result, "market_breadth")
    assert breadth["status"] == "watch"
    assert "60日线" in breadth["message"]
    assert "20日上涨行业" in breadth["message"]


def test_industry_crowding_is_local_avoidance_not_global_hard_stop() -> None:
    config = load_quant_brief_config()
    panel = pl.DataFrame(
        [
            {
                "industry_name": "电子",
                "industry_code": "801080",
                "status": "ok",
                "tcr": 26.0,
                "crowding_temperature": 95.0,
            }
        ]
    )
    result = evaluate_risk_gates(config, {}, {}, panel, None)

    industry = _gate(result, "industry_crowding")
    assert industry["status"] == "triggered"
    assert industry["severity"] == "local"
    assert result["hard_stop"] is False


def test_risk_gates_report_partial_when_required_facts_are_missing() -> None:
    result = evaluate_risk_gates(load_quant_brief_config(), {}, {}, pl.DataFrame(), None)

    assert result["status"] == "partial"
    assert result["hard_stop"] is False
    assert all(gate["status"] == "insufficient" for gate in result["gates"])


def _facts(values: list[tuple[str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "category": ["metric_value"] * len(values),
            "dimension": ["fund_flow"] * len(values),
            "metric_id": [item[0] for item in values],
            "value_float": [item[1] for item in values],
            "metric_date": [date(2026, 8, 14)] * len(values),
            "as_of_date": [date(2026, 8, 14)] * len(values),
            "status": ["ok"] * len(values),
            "sample_size": [31] * len(values),
        }
    )


def _clear_panel() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "industry_name": "煤炭",
                "industry_code": "801950",
                "status": "ok",
                "tcr": 3.0,
                "crowding_temperature": 40.0,
            }
        ]
    )


def _gate(result: dict[str, Any], gate_id: str) -> dict[str, Any]:
    return next(gate for gate in result["gates"] if gate["id"] == gate_id)
