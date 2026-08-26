"""量化投研简报解读与渲染测试。"""

from datetime import date
from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import load_quant_brief_config
from stock_reporting.interpretation.quant_brief.cross_cycle import (
    cross_cycle_summary,
    evaluate_cross_cycle,
)
from stock_reporting.interpretation.quant_brief.extreme_state import evaluate_extreme_state
from stock_reporting.interpretation.quant_brief.interpretation import (
    evaluate_macro,
    evaluate_nature,
    evaluate_risk_gates,
    evaluate_sector,
    evaluate_veto,
)
from stock_reporting.interpretation.quant_brief.risk_gates import evaluate_divergence_gate
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

    assert "## 1. 跨周期胜率赔率矩阵" in markdown
    assert "## 2. 极端状态窗口与执行链" in markdown
    assert "## 3. 宏观定基调" in markdown
    assert "## 0. 风控闸门总览" in markdown
    assert "## 4. 量价判性质" in markdown
    assert "## 5. 微观排雷与一票否决" in markdown
    assert "## 6. 中观选方向" in markdown
    assert "主力资金与杠杆健康度" in markdown
    assert brief["veto"]["top5pct"]["value"] == 0.32
    assert "结构领先但未进入优先方向" in markdown
    assert brief["cross_cycle"]["rules_version"] == "odds-matrix-v1"


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


def test_divergence_gate_marks_hot_extreme_as_watch() -> None:
    config = load_quant_brief_config()
    gate = evaluate_divergence_gate(
        config,
        {
            "fast_slow": {
                "status": "ready",
                "fast_temperature": 65.0,
                "slow_temperature": 40.0,
                "divergence": 25.0,
            }
        },
    )

    assert gate["status"] == "watch"
    assert gate["severity"] == "watch"
    assert "派发警惕" in gate["message"]
    assert "收紧止盈" in gate["action"]


def test_divergence_gate_marks_ice_extreme_as_observation_without_hard_stop() -> None:
    config = load_quant_brief_config()
    gate = evaluate_divergence_gate(
        config,
        {
            "fast_slow": {
                "status": "ready",
                "fast_temperature": 30.0,
                "slow_temperature": 60.0,
                "divergence": -30.0,
            }
        },
    )

    assert gate["status"] == "clear"
    assert gate["severity"] == "none"
    assert "底部反攻" in gate["message"]
    assert gate["action"] != ""


def test_divergence_gate_clear_when_synchronized() -> None:
    config = load_quant_brief_config()
    gate = evaluate_divergence_gate(
        config,
        {
            "fast_slow": {
                "status": "ready",
                "fast_temperature": 50.0,
                "slow_temperature": 50.0,
                "divergence": 0.0,
            }
        },
    )

    assert gate["status"] == "clear"
    assert "未出现深度背离" in gate["message"]


def test_divergence_gate_hot_requires_high_fast_even_at_extreme_divergence() -> None:
    config = load_quant_brief_config()
    gate = evaluate_divergence_gate(
        config,
        {
            "fast_slow": {
                "status": "ready",
                "fast_temperature": 55.0,
                "slow_temperature": 30.0,
                "divergence": 25.0,
            }
        },
    )

    # 背离够深但短线温度 55 < 60：不触发派发观察
    assert gate["status"] == "clear"


def test_divergence_gate_insufficient_without_fast_slow() -> None:
    config = load_quant_brief_config()
    gate = evaluate_divergence_gate(config, {})

    assert gate["status"] == "insufficient"
    assert gate["severity"] == "none"


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


def _market_scores(
    *,
    as_of: str = "2026-08-25",
    div_level: str = "synchronized",
    fast: float = 59.19,
    slow: float = 57.28,
    divergence: float = 1.91,
    short_5d: float = 40.84,
    transmission: str = "pending_next_ashare_session",
    background_pressure: float = 80.74,
    valuation: float = 54.24,
    macro_liquidity: float = 61.35,
    composite: float = 58.23,
) -> dict[str, Any]:
    return {
        "as_of_date": as_of,
        "composite": {"temperature": composite},
        "dimensions": [
            {"dimension_id": "valuation", "temperature": valuation},
            {"dimension_id": "macro_liquidity", "temperature": macro_liquidity},
        ],
        "fast_slow": {
            "status": "ready",
            "fast_temperature": fast,
            "slow_temperature": slow,
            "divergence": divergence,
            "divergence_level": div_level,
        },
        "short_term": [
            {"window": 5, "temperature": short_5d},
            {"window": 10, "temperature": short_5d + 6.0},
        ],
        "external_risk": {
            "background_pressure": background_pressure,
            "transmission_status": transmission,
        },
    }


def _industry_scores(
    *,
    diffusion_60d: float = 12.9,
    crowded_share: float | None = 9.68,
) -> dict[str, Any]:
    return {
        "trend_diagnostics": {"positive_return_60d_share": diffusion_60d},
        "structure_health": {"crowded_industry_share": crowded_share},
    }


def test_cross_cycle_standard_when_mid_win_and_mid_odds() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        _market_scores(),
        _industry_scores(),
        market_facts=_facts(
            [("above_ma60_share", 0.4453), ("main_money_net_inflow_share_20d_cum", -0.011)]
        ),
    )

    assert result["status"] == "ready"
    assert result["win_level"] == "中"
    assert result["odds_level"] == "中"
    assert result["quadrature"] == "standard"
    assert result["position_adjustment_pp"] == 0.0
    assert any("背离同步" in item for item in result["win_parts"])


def test_cross_cycle_core_when_high_win_and_high_odds() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        _market_scores(
            div_level="synchronized",
            fast=55.0,
            slow=45.0,
            short_5d=30.0,
            transmission="",
            background_pressure=50.0,
            valuation=35.0,
            macro_liquidity=30.0,
        ),
        _industry_scores(diffusion_60d=20.0, crowded_share=0.0),
        market_facts=_facts(
            [("above_ma60_share", 0.65), ("main_money_net_inflow_share_20d_cum", 0.01)]
        ),
    )

    assert result["win_level"] == "高"
    assert result["odds_level"] == "高"
    assert result["quadrature"] == "core"
    assert result["position_adjustment_pp"] == 0.0
    assert "核心仓" in result["adjustment_note"]


def test_cross_cycle_left_when_high_odds_and_low_win() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        _market_scores(
            div_level="extreme",
            fast=30.0,
            slow=45.0,
            divergence=-30.0,
            short_5d=30.0,
            transmission="pending_next_ashare_session",
            background_pressure=50.0,
            valuation=35.0,
            macro_liquidity=30.0,
        ),
        _industry_scores(diffusion_60d=20.0, crowded_share=0.0),
        market_facts=_facts(
            [("above_ma60_share", 0.20), ("main_money_net_inflow_share_20d_cum", -0.02)]
        ),
    )

    assert result["win_level"] == "低"
    assert result["odds_level"] == "高"
    assert result["quadrature"] == "left"
    assert result["position_adjustment_pp"] == -7.0
    assert "试错仓" in result["adjustment_note"]


def test_cross_cycle_avoid_when_low_win_and_low_odds() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        _market_scores(
            div_level="extreme",
            fast=72.0,
            slow=70.0,
            divergence=30.0,
            short_5d=70.0,
            transmission="pending_next_ashare_session",
            background_pressure=85.0,
            valuation=75.0,
            macro_liquidity=70.0,
        ),
        _industry_scores(diffusion_60d=65.0, crowded_share=12.0),
        market_facts=_facts(
            [("above_ma60_share", 0.20), ("main_money_net_inflow_share_20d_cum", -0.02)]
        ),
    )

    assert result["win_level"] == "低"
    assert result["odds_level"] == "低"
    assert result["quadrature"] == "avoid"
    assert result["position_adjustment_pp"] == -5.0


def test_cross_cycle_trajectory_convergence_adds_win_adj() -> None:
    config = load_quant_brief_config()
    history = pl.DataFrame(
        {
            "as_of_date": [date(2026, 8, 24), date(2026, 8, 25)],
            "divergence_level": ["extreme", "synchronized"],
            "composite_temperature": [48.98, 58.23],
            "slow_temperature": [57.82, 57.28],
            "is_latest_for_date": [True, True],
        }
    )
    result = evaluate_cross_cycle(
        config,
        _market_scores(),
        _industry_scores(),
        market_facts=_facts(
            [("above_ma60_share", 0.4453), ("main_money_net_inflow_share_20d_cum", -0.011)]
        ),
        history=history,
    )

    # 同步 +10、资金流出 -10、外盘待确认 -10（v1 校准后）
    assert result["win_raw"] == -10.0
    # 收敛确认 +5、近5日复合温度上行 +5（v1 校准后弱化）
    assert result["win_adj"] == 10.0
    assert result["win_score"] == 0.0
    # 慢温 5 日变化 -0.54pp <= -0.5 → -5
    assert result["odds_adj"] == -5.0
    trajectory = result["trajectory"]
    assert trajectory is not None
    assert "收敛确认" in trajectory["divergence_transition"]
    assert trajectory["d5_composite_direction"] == "up"


def test_cross_cycle_degraded_when_inputs_missing() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        {"as_of_date": "2026-08-25"},
        _industry_scores(),
    )

    assert result["status"] == "degraded"
    assert result["missing"]
    assert result["quadrature"] == "standard"


def test_cross_cycle_rules_version_and_summary() -> None:
    config = load_quant_brief_config()
    result = evaluate_cross_cycle(
        config,
        _market_scores(),
        _industry_scores(),
        market_facts=_facts(
            [("above_ma60_share", 0.4453), ("main_money_net_inflow_share_20d_cum", -0.011)]
        ),
    )

    assert result["rules_version"] == config.cross_cycle.rules_version == "odds-matrix-v1"
    summary = cross_cycle_summary(result)
    assert "胜率环境" in summary
    assert "赔率环境" in summary
    assert "象限" in summary


def _extreme_panel(rows: list[tuple[str, float, float]]) -> pl.DataFrame:
    """构造行业面板：(名称, tcr, crowding_temperature)。"""
    return pl.DataFrame(
        [
            {
                "industry_name": name,
                "industry_code": f"80{i:04d}.SI",
                "status": "ok",
                "tcr": tcr,
                "crowding_temperature": crowding,
            }
            for i, (name, tcr, crowding) in enumerate(rows)
        ]
    )


def test_extreme_state_hot_window_sets_bias_and_rank() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=65.3),
        _extreme_panel([("电子", 5.0, 40.0)]),
    )

    assert result["status"] == "ready"
    assert result["hot_window"]["triggered"] is True
    assert result["composite_window_rank"] == "hot"
    assert result["position_bias_pp"] == -10.0
    assert "只减不加" in result["action"]
    assert "hot_window" in result["windows"]


def test_extreme_state_frozen_by_cold_composite() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=40.0),
        _extreme_panel([("电子", 5.0, 40.0)]),
    )

    assert result["frozen_window"]["triggered"] is True
    assert result["composite_window_rank"] == "frozen"
    assert result["position_bias_pp"] == -7.0
    assert "左侧分批" in result["action"]


def test_extreme_state_frozen_by_ice_divergence() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=50.0, div_level="extreme", fast=30.0, slow=58.0, divergence=-20.0),
        _extreme_panel([("电子", 5.0, 40.0)]),
    )

    assert result["frozen_window"]["triggered"] is True
    assert result["frozen_window"]["ice_divergence"] is True
    assert result["composite_window_rank"] == "frozen"


def test_extreme_state_crowded_window_keeps_total_position() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=55.0),
        _extreme_panel([("电子", 26.0, 40.0), ("通信", 5.0, 95.0), ("银行", 1.0, 30.0)]),
    )

    assert result["crowded_window"]["triggered"] is True
    assert result["crowded_window"]["crowded_count"] == 2
    assert "电子" in result["crowded_window"]["crowded_industries"]
    assert "通信" in result["crowded_window"]["crowded_industries"]
    assert result["position_bias_pp"] == 0.0
    assert result["composite_window_rank"] == "crowded_only"
    assert "crowded_window" in result["windows"]


def test_extreme_state_hot_overrides_frozen() -> None:
    config = load_quant_brief_config()
    # 同时满足 hot（>60）与冰点背离条件：hot 优先
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=62.0, div_level="extreme", fast=25.0, slow=60.0, divergence=-25.0),
        _extreme_panel([]),
    )

    assert result["hot_window"]["triggered"] is True
    assert result["frozen_window"]["triggered"] is False
    assert result["composite_window_rank"] == "hot"


def test_extreme_state_normal_without_windows() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        _market_scores(composite=55.0),
        _extreme_panel([("银行", 1.0, 30.0)]),
    )

    assert result["windows"] == []
    assert result["composite_window_rank"] == "normal"
    assert result["position_bias_pp"] == 0.0
    assert "无极端状态窗口" in result["action"]


def test_extreme_state_degraded_when_temperature_missing() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(
        config,
        {"fast_slow": {"fast_temperature": 30.0, "slow_temperature": 60.0, "divergence": -20.0}},
        _extreme_panel([]),
    )

    assert result["status"] == "degraded"
    assert "temperature" in result["missing"]


def test_extreme_state_rules_version() -> None:
    config = load_quant_brief_config()
    result = evaluate_extreme_state(config, _market_scores(composite=55.0), _extreme_panel([]))

    assert result["rules_version"] == config.extreme_rules_version == "extreme-route-v1"
