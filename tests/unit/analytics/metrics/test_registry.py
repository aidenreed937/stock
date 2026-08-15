from stock.analytics.metrics import EntityType, MetricDomain, MetricRegistry, MetricSpec


def test_registry_filters_specs_by_domain_and_entity_type() -> None:
    specs = (
        MetricSpec(
            metric_id="return_20d",
            name="20日收益率",
            domain=MetricDomain.PERFORMANCE,
            entity_type=EntityType.STOCK,
        ),
        MetricSpec(
            metric_id="pe_percentile",
            name="PE历史分位",
            domain=MetricDomain.VALUATION,
            entity_type=EntityType.INDEX,
        ),
    )

    registry = MetricRegistry(specs)

    assert registry.get("return_20d").name == "20日收益率"
    assert registry.select(domain=MetricDomain.PERFORMANCE) == (specs[0],)
    assert registry.select(entity_type=EntityType.INDEX) == (specs[1],)
