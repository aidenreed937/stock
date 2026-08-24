"""统一 metrics/features 双轨调度门面 (analytics.api) 单测。"""

from datetime import date

import polars as pl
import pytest

from stock_analytics.api import (
    AnalyticsContext,
    compute_features,
    compute_metrics,
    list_features,
    list_metrics,
)
from stock_analytics.features.registry import FeatureRegistry
from stock_analytics.features.spec import FeatureKind, FeatureSpec
from stock_analytics.features.store import FeatureStore
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.registry import MetricRegistry
from stock_analytics.metrics.spec import MetricDomain, MetricSpec
from stock_core.models.market import EntityType

# ---------- compute_metrics ----------


def test_compute_metrics_dispatches_via_default_registry_and_calculators() -> None:
    spec = MetricSpec(
        metric_id="custom_metric",
        name="自定义指标",
        domain=MetricDomain.PERFORMANCE,
        entity_type=EntityType.INDEX,
        output_columns=("value",),
    )
    registry = MetricRegistry((spec,))

    def calc(context: MetricContext, metric_spec: MetricSpec) -> pl.DataFrame:
        return pl.DataFrame({"value": [3.14]})

    results = compute_metrics(
        ["custom_metric"],
        registry=registry,
        calculators={"custom_metric": calc},
    )

    assert len(results) == 1
    assert results[0].metric_id == "custom_metric"
    assert results[0].frame["value"].to_list() == [3.14]


def test_compute_metrics_raises_for_unknown_metric() -> None:
    with pytest.raises(KeyError, match="未知指标"):
        compute_metrics(["not_a_metric"])


def test_compute_metrics_uses_context_dates_for_metric_context() -> None:
    ctx = AnalyticsContext(target_date=date(2026, 8, 21), start_date=date(2026, 8, 1))
    metric_ctx = ctx.resolve_metric_context()
    assert metric_ctx.target_date == date(2026, 8, 21)
    assert metric_ctx.start_date == date(2026, 8, 1)
    assert metric_ctx.resolve_end_date() == date(2026, 8, 21)


def test_compute_metrics_prefers_explicit_metric_context() -> None:
    explicit = MetricContext(target_date=date(2026, 8, 20))
    ctx = AnalyticsContext(target_date=date(2026, 8, 21), metric_context=explicit)
    assert ctx.resolve_metric_context() is explicit


# ---------- compute_features ----------


def test_compute_features_returns_empty_when_mart_not_built(tmp_path) -> None:
    ctx = AnalyticsContext(feature_store=FeatureStore(mart_dir=tmp_path))
    out = compute_features(["total_turnover"], context=ctx)
    assert out.is_empty()


def test_compute_features_projects_requested_columns(tmp_path) -> None:
    store = FeatureStore(mart_dir=tmp_path)
    panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 20), date(2026, 8, 21)],
            "total_turnover": [1.0e11, 1.2e11],
            "adv_dec_ratio": [2.0, 3.0],
        }
    )
    store.save_market_daily(panel)
    ctx = AnalyticsContext(feature_store=store)

    out = compute_features(["total_turnover"], context=ctx)
    assert out.columns == ["trade_date", "total_turnover"]
    assert out.height == 2

    out_all = compute_features([], context=ctx)
    assert "total_turnover" in out_all.columns
    assert "adv_dec_ratio" in out_all.columns


def test_compute_features_respects_date_filters(tmp_path) -> None:
    store = FeatureStore(mart_dir=tmp_path)
    panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 20), date(2026, 8, 21)],
            "total_turnover": [1.0e11, 1.2e11],
        }
    )
    store.save_market_daily(panel)
    ctx = AnalyticsContext(
        feature_store=store,
        start_date=date(2026, 8, 21),
        end_date=date(2026, 8, 21),
    )
    out = compute_features(["total_turnover"], context=ctx)
    assert out.height == 1
    assert out["trade_date"].to_list() == [date(2026, 8, 21)]


# ---------- list_metrics / list_features ----------


def test_list_metrics_returns_all_and_filters_by_domain_entity() -> None:
    all_metrics = list_metrics()
    assert len(all_metrics) >= 60  # 内置注册表 67 个指标

    valuation = list_metrics(domain=MetricDomain.VALUATION)
    assert valuation
    assert all(spec.domain == MetricDomain.VALUATION for spec in valuation)

    industry = list_metrics(entity_type=EntityType.INDUSTRY)
    assert industry
    assert all(spec.entity_type == EntityType.INDUSTRY for spec in industry)
    assert any(spec.metric_id == "sw_industry_pe" for spec in industry)


def test_list_features_returns_all_and_filters_by_kind_entity() -> None:
    all_features = list_features()
    assert all_features
    assert all(isinstance(spec, FeatureSpec) for spec in all_features)

    factors = list_features(kind=FeatureKind.FACTOR)
    assert all(spec.kind == FeatureKind.FACTOR for spec in factors)

    market = list_features(entity_type=EntityType.MARKET)
    assert market
    assert all(spec.entity_type == EntityType.MARKET for spec in market)


def test_list_features_reflects_registry_content() -> None:
    registered = set(FeatureRegistry._registry.keys())
    listed = {spec.feature_id for spec in list_features()}
    assert listed == registered
