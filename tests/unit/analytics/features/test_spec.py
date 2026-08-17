"""Feature 契约与注册表单元测试。"""

from stock.analytics.features.registry import FeatureRegistry
from stock.analytics.features.spec import (
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
