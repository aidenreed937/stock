"""市场温度计评分测试。"""

from datetime import date

import polars as pl
import pytest

from stock_analytics.pipelines.market_temperature.facts import FACT_SCHEMA
from stock_analytics.pipelines.market_temperature.scoring import build_scores
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
