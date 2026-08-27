"""市场温度计评分测试。"""

from datetime import date

import polars as pl
import pytest

from stock_analytics.marts.shared.market_temperature.facts import FACT_SCHEMA
from stock_analytics.pipelines.market_temperature.scoring import (
    _fast_slow_temperatures,
    build_scores,
)
from stock_reporting.interpretation.market_temperature.config import (
    DimensionConfig,
    MarketTemperatureConfig,
    MetricInputConfig,
)
from stock_reporting.interpretation.market_temperature.external_risk_config import (
    ExternalRiskConfig,
    ExternalShockConfig,
    ExternalShockRuleConfig,
)


def test_build_scores_uses_configured_metric_weights() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("fundamental", "a_temperature", 40.0),
            _metric_fact("fundamental", "b_temperature", 80.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(5, 10),
        dimensions=(
            DimensionConfig(
                id="fundamental",
                name="基本面",
                weight=1.0,
                metrics=(
                    MetricInputConfig("a_temperature", source="derived", weight=0.25),
                    MetricInputConfig("b_temperature", source="derived", weight=0.75),
                ),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["dimensions"][0]["temperature"] == pytest.approx(70.0)
    assert scores["composite"]["temperature"] == pytest.approx(70.0)
    assert scores["systemic_risk"]["level"] in {"低到中等", "中等", "中等偏高", "高"}


def test_build_scores_converts_zscore_to_temperature() -> None:
    facts = pl.DataFrame(
        [_metric_fact("fund_flow", "margin_buy_share_zscore_60d", 0.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="fund_flow",
                name="资金面",
                weight=1.0,
                metrics=(MetricInputConfig("margin_buy_share_zscore_60d", weight=1.0),),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["dimensions"][0]["temperature"] == pytest.approx(50.0)


def test_build_scores_converts_erp_percentile_with_inverse_direction() -> None:
    facts = pl.DataFrame(
        [_metric_fact("valuation", "equity_risk_premium_percentile_5y", 20.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="valuation",
                name="估值面",
                weight=1.0,
                metrics=(
                    MetricInputConfig(
                        "equity_risk_premium_percentile_5y",
                        direction="inverse",
                        weight=1.0,
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["dimensions"][0]["temperature"] == pytest.approx(80.0)


def test_build_scores_ignores_zero_weight_observation_metrics() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 60.0),
            _metric_fact(
                "macro_liquidity",
                "macro_fred_fedfunds_temperature",
                None,
                status="insufficient",
            ),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=1.0,
                metrics=(
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=1.0,
                    ),
                    MetricInputConfig(
                        "macro_fred_fedfunds_temperature",
                        source="derived",
                        weight=0.0,
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["dimensions"][0]["temperature"] == pytest.approx(60.0)
    assert scores["dimensions"][0]["metric_count"] == 1
    assert scores["dimensions"][0]["ok_metric_count"] == 1
    assert scores["dimensions"][0]["reason"] == "指标事实已温度化"


def test_build_scores_adds_configured_external_risk_without_changing_composite() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("valuation", "valuation_temperature", 60.0),
            _metric_fact("macro_liquidity", "macro_external_pressure_temperature", 74.61),
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 49.41),
            _metric_fact("macro_liquidity", "macro_nasdaq_1d_return", -0.0133),
            _metric_fact("macro_liquidity", "macro_vix_1d_change", 0.0428),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(_dimension_config("valuation", "估值面", "valuation_temperature"),),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 18), facts=facts)

    assert scores["composite"]["temperature"] == pytest.approx(60.0)
    external_risk = scores["external_risk"]
    assert external_risk["background_pressure"] == pytest.approx(74.61)
    assert external_risk["environment_temperature"] == pytest.approx(49.41)
    assert external_risk["shock_status"] == "short_term_shock"
    assert external_risk["transmission_status"] == "pending_next_ashare_session"
    assert external_risk["triggered_rules"][0]["metric_id"] == "macro_nasdaq_1d_return"


def test_build_scores_uses_configured_external_shock_thresholds() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("valuation", "valuation_temperature", 60.0),
            _metric_fact("macro_liquidity", "macro_nasdaq_1d_return", -0.015),
            _metric_fact("macro_liquidity", "macro_vix_1d_change", 0.05),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(_dimension_config("valuation", "估值面", "valuation_temperature"),),
        datasets=(),
        external_risk=ExternalRiskConfig(
            shock=ExternalShockConfig(
                min_trigger_count=2,
                rules=(
                    ExternalShockRuleConfig("macro_nasdaq_1d_return", "lte", -0.02, "纳斯达克"),
                    ExternalShockRuleConfig("macro_vix_1d_change", "gte", 0.04, "VIX"),
                ),
            ),
            transmission_status_without_shock="custom_no_shock",
        ),
    )

    external_risk = build_scores(
        config,
        as_of_date=date(2026, 8, 18),
        facts=facts,
    )["external_risk"]

    assert external_risk["shock_status"] == "no_shock"
    assert external_risk["transmission_status"] == "custom_no_shock"
    assert external_risk["triggered_rule_count"] == 1


def test_build_scores_adds_systemic_risk_summary() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("valuation", "valuation_temperature", 85.0),
            _metric_fact("fund_flow", "fund_flow_temperature", 45.0),
            _metric_fact("technical", "technical_temperature", 70.0),
            _metric_fact("sentiment", "sentiment_temperature", 55.0),
            _metric_fact("macro_liquidity", "macro_temperature", 60.0),
            _metric_fact("fundamental", "fundamental_temperature", 62.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            _dimension_config("valuation", "估值面", "valuation_temperature"),
            _dimension_config("fund_flow", "资金面", "fund_flow_temperature"),
            _dimension_config("technical", "技术面", "technical_temperature"),
            _dimension_config("sentiment", "情绪面", "sentiment_temperature"),
            _dimension_config("macro_liquidity", "宏观流动性", "macro_temperature"),
            _dimension_config("fundamental", "基本面", "fundamental_temperature"),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["systemic_risk"]["level"] == "中等偏高"
    assert "估值面 85.00 已进入高温" in scores["systemic_risk"]["red_flags"][0]
    assert any("技术面偏热" in item for item in scores["systemic_risk"]["warnings"])
    trace = scores["systemic_risk"]["decision_trace"]
    assert trace["rule_version"] == "systemic-risk-v3"
    assert trace["final_level"] == "中等偏高"
    assert trace["triggered_rules"][0]["rule_id"] == "valuation_gte_80"


def test_build_scores_reduces_stale_metric_weight() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact(
                "fundamental",
                "fs_profit_growth_temperature",
                40.0,
                note="stale_days=136; report_date=2026-03-31; profit_positive_share",
            ),
            _metric_fact(
                "fundamental",
                "fs_revenue_growth_temperature",
                60.0,
                note="stale_days=136; report_date=2026-03-31; revenue_positive_share",
            ),
            _metric_fact(
                "fundamental",
                "forecast_positive_temperature",
                80.0,
                note="ann_window=2026-07-20..2026-08-14",
            ),
            _metric_fact(
                "fundamental",
                "report_revision_temperature",
                70.0,
                note="ann_window=2026-07-20..2026-08-14",
            ),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="fundamental",
                name="基本面",
                weight=1.0,
                stale_after_days=90,
                stale_weight_scale=0.4,
                metrics=(
                    MetricInputConfig(
                        "fs_profit_growth_temperature", source="derived", weight=0.25
                    ),
                    MetricInputConfig(
                        "fs_revenue_growth_temperature", source="derived", weight=0.20
                    ),
                    MetricInputConfig(
                        "forecast_positive_temperature", source="derived", weight=0.25
                    ),
                    MetricInputConfig("report_revision_temperature", source="derived", weight=0.30),
                ),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    # stale 权重 ×0.4 后让出的权重自动摊给 fast 指标
    assert scores["dimensions"][0]["temperature"] == pytest.approx(68.22)


def test_build_scores_keeps_fresh_metric_weight() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact(
                "fundamental",
                "fs_profit_growth_temperature",
                40.0,
                note="stale_days=60; report_date=2026-06-30",
            ),
            _metric_fact(
                "fundamental",
                "report_revision_temperature",
                80.0,
                note="ann_window=2026-07-20..2026-08-14",
            ),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="fundamental",
                name="基本面",
                weight=1.0,
                stale_after_days=90,
                stale_weight_scale=0.4,
                metrics=(
                    MetricInputConfig("fs_profit_growth_temperature", source="derived", weight=0.4),
                    MetricInputConfig("report_revision_temperature", source="derived", weight=0.6),
                ),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    # stale_days=60 未超过 90 阈值，按原权重合成
    assert scores["dimensions"][0]["temperature"] == pytest.approx(64.0)


def test_build_scores_reports_data_freshness() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact(
                "fundamental",
                "fs_profit_growth_temperature",
                40.0,
                note="stale_days=136; report_date=2026-03-31; profit_positive_share",
            ),
            _metric_fact(
                "fundamental",
                "report_revision_temperature",
                70.0,
                note="ann_window=2026-07-20..2026-08-14",
            ),
            _metric_fact("valuation", "valuation_temperature", 55.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="fundamental",
                name="基本面",
                weight=1.0,
                stale_after_days=90,
                stale_weight_scale=0.4,
                metrics=(
                    MetricInputConfig("fs_profit_growth_temperature", source="derived", weight=0.5),
                    MetricInputConfig("report_revision_temperature", source="derived", weight=0.5),
                ),
            ),
            DimensionConfig(
                id="valuation",
                name="估值面",
                weight=1.0,
                metrics=(MetricInputConfig("valuation_temperature", weight=1.0),),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    fundamental = scores["dimensions"][0]["data_freshness"]
    assert fundamental["latest_data_date"] == "2026-08-14"
    assert fundamental["stale_metric_count"] == 1
    assert fundamental["stale_metrics"] == [
        {"metric_id": "fs_profit_growth_temperature", "data_date": "2026-03-31"}
    ]
    assert scores["dimensions"][1]["data_freshness"]["stale_metric_count"] == 0
    top = scores["data_freshness"]
    assert top["stale_metric_count"] == 1
    assert top["stale_metrics"][0]["metric_id"] == "fs_profit_growth_temperature"
    assert top["stale_metrics"][0]["dimension"] == "fundamental"


def test_build_scores_separates_sentiment_subgroups() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("sentiment", "advance_share", 0.08),
            _metric_fact("sentiment", "limit_event_temperature", 20.0),
            _metric_fact("sentiment", "turnover_rate_percentile_1250d", 90.0),
            _metric_fact("sentiment", "investor_account_temperature", 90.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="sentiment",
                name="情绪面",
                weight=1.0,
                metrics=(
                    MetricInputConfig("advance_share", weight=0.25),
                    MetricInputConfig("limit_event_temperature", weight=0.25),
                    MetricInputConfig(
                        "turnover_rate_percentile_1250d", weight=0.40, subgroup="activity"
                    ),
                    MetricInputConfig(
                        "investor_account_temperature",
                        source="derived",
                        weight=0.10,
                        subgroup="slow",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    sentiment = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    assert sentiment["temperature"] == pytest.approx(14.0)
    assert sentiment["temperature_source"] == "daily"
    assert sentiment["subgroups"] == {"activity": 90.0, "slow": 90.0}


def test_build_scores_falls_back_to_activity_subgroup_when_daily_is_missing() -> None:
    facts = pl.DataFrame(
        [_metric_fact("sentiment", "turnover_rate_percentile_1250d", 90.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="sentiment",
                name="情绪面",
                weight=1.0,
                metrics=(
                    MetricInputConfig("advance_share", weight=0.5),
                    MetricInputConfig(
                        "turnover_rate_percentile_1250d", weight=0.5, subgroup="activity"
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    sentiment = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    assert sentiment["temperature"] == pytest.approx(90.0)
    assert sentiment["temperature_source"] == "activity"
    assert "主温度已降级为活跃水位口径" in sentiment["reason"]


def test_build_scores_builds_structured_comparison_drivers() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("technical", "return_20d", 0.02),
            _metric_fact("fund_flow", "fund_flow_temperature", 40.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="technical",
                name="技术面",
                weight=0.6,
                metrics=(MetricInputConfig("return_20d", weight=1.0),),
            ),
            DimensionConfig(
                id="fund_flow",
                name="资金面",
                weight=0.4,
                metrics=(MetricInputConfig("fund_flow_temperature", weight=1.0),),
            ),
        ),
        datasets=(),
    )

    scores = build_scores(
        config,
        as_of_date=date(2026, 8, 14),
        facts=facts,
        previous_scores={
            "as_of_date": "2026-08-13",
            "composite": {"temperature": 40.0},
            "dimensions": [
                {"dimension_id": "technical", "temperature": 40.0},
                {"dimension_id": "fund_flow", "temperature": 50.0},
            ],
        },
    )

    drivers = scores["drivers"]
    assert drivers["status"] == "ok"
    assert drivers["comparison_as_of"] == "2026-08-13"
    assert drivers["composite_delta"] == pytest.approx(12.0)
    assert drivers["top_contributors"][0]["dimension_id"] == "technical"
    assert drivers["top_contributors"][0]["direction"] == "warming"


def test_build_scores_builds_fast_slow_block() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("valuation", "valuation_temperature", 54.24),
            _metric_fact("fund_flow", "fund_flow_temperature", 50.34),
            _metric_fact("sentiment", "sentiment_temperature", 73.39),
            _metric_fact("technical", "technical_temperature", 56.79),
            _metric_fact("fundamental", "fundamental_temperature", 57.25),
            _metric_fact("macro_liquidity", "macro_liquidity_temperature", 61.16),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=_six_dimension_configs(),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 25), facts=facts)
    fast_slow = scores["fast_slow"]

    assert fast_slow["status"] == "ready"
    # 快 = (资金50.34*0.2 + 情绪73.39*0.15 + 技术56.79*0.15) / 0.5
    assert fast_slow["fast_temperature"] == pytest.approx(
        round((50.34 * 0.2 + 73.39 * 0.15 + 56.79 * 0.15) / 0.5, 2)
    )
    # 慢 = (估值54.24*0.2 + 基本面57.25*0.15 + 宏观61.16*0.15) / 0.5
    assert fast_slow["slow_temperature"] == pytest.approx(
        round((54.24 * 0.2 + 57.25 * 0.15 + 61.16 * 0.15) / 0.5, 2)
    )
    assert fast_slow["divergence"] == pytest.approx(1.97)


def _six_dimension_configs() -> tuple[DimensionConfig, ...]:
    return (
        _weighted_dimension_config("valuation", "估值面", "valuation_temperature", 0.20),
        _weighted_dimension_config("fund_flow", "资金面", "fund_flow_temperature", 0.20),
        _weighted_dimension_config("technical", "技术面", "technical_temperature", 0.15),
        _weighted_dimension_config("sentiment", "情绪面", "sentiment_temperature", 0.15),
        _weighted_dimension_config(
            "macro_liquidity", "宏观流动性", "macro_liquidity_temperature", 0.15
        ),
        _weighted_dimension_config("fundamental", "基本面", "fundamental_temperature", 0.15),
    )


def _weighted_dimension_config(dimension_id, name, metric_id, weight) -> DimensionConfig:
    return DimensionConfig(
        id=dimension_id,
        name=name,
        weight=weight,
        metrics=(MetricInputConfig(metric_id, source="derived", weight=1.0),),
    )


def test_fast_slow_block_flags_extreme_divergence() -> None:
    dims = [
        {"dimension_id": "fund_flow", "temperature": 29.21, "weight": 0.20},
        {"dimension_id": "sentiment", "temperature": 10.6, "weight": 0.15},
        {"dimension_id": "technical", "temperature": 25.0, "weight": 0.15},
        {"dimension_id": "valuation", "temperature": 62.0, "weight": 0.20},
        {"dimension_id": "fundamental", "temperature": 58.0, "weight": 0.15},
        {"dimension_id": "macro_liquidity", "temperature": 56.5, "weight": 0.15},
    ]
    fast_slow = _fast_slow_temperatures(dims)

    assert fast_slow["status"] == "ready"
    assert fast_slow["divergence"] < -15
    assert fast_slow["divergence_level"] == "extreme"
    assert fast_slow["divergence_label"] == "深度背离"


def test_build_scores_fast_slow_insufficient_when_group_missing() -> None:
    facts = pl.DataFrame(
        [_metric_fact("valuation", "valuation_temperature", 60.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(_dimension_config("valuation", "估值面", "valuation_temperature"),),
        datasets=(),
    )

    scores = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)

    assert scores["fast_slow"]["status"] == "insufficient"


def test_build_scores_composes_macro_liquidity_domestic_external_capped() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("macro_liquidity", "macro_bond_yield_10y_temperature", 60.0),
            _metric_fact("macro_liquidity", "macro_shibor_on_temperature", 80.0),
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 90.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                subgroup_external_cap=0.25,
                metrics=(
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature",
                        source="derived",
                        weight=0.18,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_shibor_on_temperature",
                        source="derived",
                        weight=0.12,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=0.40,
                        subgroup="external",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    dimension = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    # 国内 = (60*0.18 + 80*0.12)/0.30 = 68.0；外部 = 90.0；cap 0.25 → 68*0.75 + 90*0.25
    assert dimension["subgroups"] == {"domestic": 68.0, "external": 90.0}
    assert dimension["temperature"] == pytest.approx(73.5)
    assert dimension["temperature_source"] == "macro_domestic_capped"
    assert dimension["metric_count"] == 3
    assert dimension["ok_metric_count"] == 3
    assert "外部环境子口径贡献已按 25% 上限约束" in dimension["reason"]


def test_build_scores_macro_uses_domestic_when_external_missing() -> None:
    facts = pl.DataFrame(
        [_metric_fact("macro_liquidity", "macro_bond_yield_10y_temperature", 40.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                subgroup_external_cap=0.25,
                metrics=(
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="external",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    dimension = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    assert dimension["temperature"] == pytest.approx(40.0)
    assert "外部环境子口径贡献已按 25% 上限约束" in dimension["reason"]


def test_build_scores_macro_uses_external_when_domestic_missing() -> None:
    facts = pl.DataFrame(
        [_metric_fact("macro_liquidity", "macro_external_environment_temperature", 55.0)],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                subgroup_external_cap=0.25,
                metrics=(
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="external",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    dimension = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    assert dimension["temperature"] == pytest.approx(55.0)


def test_build_scores_macro_without_cap_keeps_legacy_daily_path() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 60.0),
            _metric_fact("macro_liquidity", "macro_bond_yield_10y_temperature", 80.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                metrics=(
                    MetricInputConfig(
                        "macro_external_environment_temperature", source="derived", weight=0.40
                    ),
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature", source="derived", weight=0.60
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    dimension = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["dimensions"][0]

    # 未配置 cap：继续按原 flat 权重合成，subgroups 不包含子口径
    assert dimension["temperature"] == pytest.approx(72.0)
    assert dimension["temperature_source"] == "daily"
    assert dimension["subgroups"] == {}


def test_systemic_risk_switches_macro_rule_to_domestic_reading() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("macro_liquidity", "macro_bond_yield_10y_temperature", 35.0),
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 70.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                subgroup_external_cap=0.25,
                metrics=(
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="external",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    risk = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["systemic_risk"]

    # 混合读数 = 35*0.75 + 70*0.25 = 43.75（≥40 不触发红旗），但国内口径 35 < 40 触发
    assert any("宏观流动性国内口径" in item for item in risk["red_flags"])
    assert any("偏紧" in item for item in risk["red_flags"])
    rule = next(
        item
        for item in risk["decision_trace"]["triggered_rules"]
        if item["rule_id"] == "macro_liquidity_lt_40"
    )
    assert rule["actual"] == pytest.approx(35.0)
    assert risk["decision_trace"]["inputs"]["macro_liquidity_domestic"] == pytest.approx(35.0)


def test_systemic_risk_macro_offset_uses_domestic_when_blend_is_below_50() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("macro_liquidity", "macro_bond_yield_10y_temperature", 60.0),
            _metric_fact("macro_liquidity", "macro_external_environment_temperature", 20.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=(
            DimensionConfig(
                id="macro_liquidity",
                name="宏观流动性",
                weight=0.15,
                subgroup_external_cap=0.25,
                metrics=(
                    MetricInputConfig(
                        "macro_bond_yield_10y_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="domestic",
                    ),
                    MetricInputConfig(
                        "macro_external_environment_temperature",
                        source="derived",
                        weight=1.0,
                        subgroup="external",
                    ),
                ),
            ),
        ),
        datasets=(),
    )

    risk = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["systemic_risk"]

    # 混合读数 = 60*0.75 + 20*0.25 = 50（恰好 ≥50），国内口径 60 依然构成缓冲因素
    rule = next(
        item
        for item in risk["decision_trace"]["triggered_rules"]
        if item["rule_id"] == "macro_liquidity_gte_50"
    )
    assert rule["actual"] == pytest.approx(60.0)
    assert any("未构成主要压力" in item for item in risk["offsets"])


def test_systemic_risk_adds_divergence_hot_red_flag() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("fund_flow", "fund_flow_temperature", 70.0),
            _metric_fact("sentiment", "sentiment_temperature", 70.0),
            _metric_fact("technical", "technical_temperature", 70.0),
            _metric_fact("valuation", "valuation_temperature", 40.0),
            _metric_fact("fundamental", "fundamental_temperature", 45.0),
            _metric_fact("macro_liquidity", "macro_liquidity_temperature", 45.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=_six_dimension_configs(),
        datasets=(),
    )

    risk = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["systemic_risk"]

    # 快 = 70，慢 = (40*0.2+45*0.15+45*0.15)/0.5 = 43，背离 +27 → 派发警惕红旗
    assert any("派发警惕" in item for item in risk["red_flags"])
    rule = next(
        item
        for item in risk["decision_trace"]["triggered_rules"]
        if item["rule_id"] == "divergence_extreme_hot_fast"
    )
    assert rule["category"] == "red_flag"
    assert rule["actual"]["divergence"] == pytest.approx(27.0)
    trace = risk["decision_trace"]
    assert trace["inputs"]["fast_slow"]["fast_temperature"] == pytest.approx(70.0)
    assert trace["inputs"]["fast_slow"]["divergence"] == pytest.approx(27.0)


def test_systemic_risk_adds_divergence_ice_offset() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("fund_flow", "fund_flow_temperature", 30.0),
            _metric_fact("sentiment", "sentiment_temperature", 30.0),
            _metric_fact("technical", "technical_temperature", 30.0),
            _metric_fact("valuation", "valuation_temperature", 55.0),
            _metric_fact("fundamental", "fundamental_temperature", 58.0),
            _metric_fact("macro_liquidity", "macro_liquidity_temperature", 60.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=_six_dimension_configs(),
        datasets=(),
    )

    risk = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["systemic_risk"]

    # 快 = 30，慢 = (55*0.2+58*0.15+60*0.15)/0.5 = 57.4，背离 -27.4 → 底部反攻缓冲
    assert any("底部反攻" in item for item in risk["offsets"])
    rule = next(
        item
        for item in risk["decision_trace"]["triggered_rules"]
        if item["rule_id"] == "divergence_extreme_cold_fast"
    )
    assert rule["category"] == "offset"
    # 冰点窗口不抬高风险等级：无红旗下等级为低到中等
    assert risk["level"] == "低到中等"


def test_systemic_risk_divergence_gate_ignores_near_boundary() -> None:
    facts = pl.DataFrame(
        [
            _metric_fact("fund_flow", "fund_flow_temperature", 58.0),
            _metric_fact("sentiment", "sentiment_temperature", 58.0),
            _metric_fact("technical", "technical_temperature", 58.0),
            _metric_fact("valuation", "valuation_temperature", 50.0),
            _metric_fact("fundamental", "fundamental_temperature", 52.0),
            _metric_fact("macro_liquidity", "macro_liquidity_temperature", 52.0),
        ],
        schema=FACT_SCHEMA,
    )
    config = MarketTemperatureConfig(
        schema_version=1,
        title="test",
        artifact_root="data/analytics/market_temperature",
        main_window=20,
        short_windows=(),
        dimensions=_six_dimension_configs(),
        datasets=(),
    )

    risk = build_scores(config, as_of_date=date(2026, 8, 14), facts=facts)["systemic_risk"]

    # 快 58（<60）且背离未达 ±15：两侧都不触发
    rule_ids = [item["rule_id"] for item in risk["decision_trace"]["triggered_rules"]]
    assert "divergence_extreme_hot_fast" not in rule_ids
    assert "divergence_extreme_cold_fast" not in rule_ids


def _metric_fact(
    dimension: str,
    metric_id: str,
    value: float | None,
    *,
    status: str = "ok",
    note: str = "",
) -> dict[str, object]:
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "test",
        "dataset": "",
        "as_of_date": date(2026, 8, 14),
        "window": 0,
        "metric_id": metric_id,
        "value_float": value,
        "value_text": "",
        "unit": "temperature" if metric_id.endswith("_temperature") else "raw",
        "sample_size": 1,
        "source": "test",
        "status": status,
        "note": note,
    }


def _dimension_config(dimension_id: str, name: str, metric_id: str) -> DimensionConfig:
    return DimensionConfig(
        id=dimension_id,
        name=name,
        weight=1.0,
        metrics=(MetricInputConfig(metric_id, source="derived"),),
    )
