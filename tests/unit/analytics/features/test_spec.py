"""Feature 契约与注册表单元测试。"""

from stock_analytics.features.registry import FeatureRegistry
from stock_analytics.features.spec import (
    EntityType,
    FeatureKind,
    FeatureUnit,
)


def test_builtin_features_registered() -> None:
    specs = FeatureRegistry.list_all()
    assert len(specs) >= 10

    turnover = FeatureRegistry.get("total_turnover")
    assert turnover.kind == FeatureKind.AGGREGATE
    assert turnover.entity_type == EntityType.MARKET
    assert turnover.unit == FeatureUnit.CNY
    assert turnover.is_materialized_wide is True


def test_feature_registry_query() -> None:
    aggregates = FeatureRegistry.list_by_kind(FeatureKind.AGGREGATE)
    assert any(s.feature_id == "total_turnover" for s in aggregates)

    indicators = FeatureRegistry.list_by_kind(FeatureKind.INDICATOR)
    assert any(s.feature_id == "above_ma20_ratio" for s in indicators)

    market_features = FeatureRegistry.list_by_entity_type(EntityType.MARKET)
    assert len(market_features) == len(FeatureRegistry.list_all())


def test_registry_covers_all_market_daily_output_features() -> None:
    expected = {
        "margin_penetration",
        "market_circ_mv",
        "option_put_call_volume_ratio",
        "option_put_call_oi_ratio",
        "option_amount",
        "option_open_interest",
        "option_near_month_amount_share",
    }

    assert expected.issubset({spec.feature_id for spec in FeatureRegistry.list_all()})
    assert FeatureRegistry.get("advance_ratio").definition_version == "v2"


def test_legacy_v1_definitions_resolvable_for_stored_rows() -> None:
    v1 = FeatureRegistry.get("advance_ratio", "v1")
    assert v1.definition_version == "v1"
    assert "总有效个股数" in v1.description

    assert FeatureRegistry.get("above_ma20_ratio", "v1").lookback_days == 20
    assert FeatureRegistry.get("above_ma60_ratio", "v1").lookback_days == 60
    assert FeatureRegistry.get("above_ma120_ratio", "v1").lookback_days == 120
    assert FeatureRegistry.get("new_high_252d_ratio", "v1").lookback_days == 252

    # 当前版本仍指向 v2
    assert FeatureRegistry.get("advance_ratio").definition_version == "v2"
