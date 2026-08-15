import polars as pl
import pytest

from stock.analytics.metrics import (
    EntityType,
    MetricContext,
    MetricDomain,
    MetricEngine,
    MetricRegistry,
    MetricSpec,
)


def test_engine_dispatches_registered_calculator() -> None:
    spec = MetricSpec(
        metric_id="return_1d",
        name="1日收益率",
        domain=MetricDomain.PERFORMANCE,
        entity_type=EntityType.INDEX,
    )
    registry = MetricRegistry((spec,))

    def calculate_return_1d(context: MetricContext, metric_spec: MetricSpec) -> pl.DataFrame:
        return pl.DataFrame({"metric_id": [metric_spec.metric_id], "value": [1.2]})

    engine = MetricEngine(registry=registry, calculators={"return_1d": calculate_return_1d})

    results = engine.compute(["return_1d"], context=MetricContext())

    assert len(results) == 1
    assert results[0].metric_id == "return_1d"
    assert results[0].frame["value"].to_list() == [1.2]


def test_engine_validates_declared_output_columns() -> None:
    spec = MetricSpec(
        metric_id="return_1d",
        name="1日收益率",
        domain=MetricDomain.PERFORMANCE,
        entity_type=EntityType.INDEX,
        output_columns=("value",),
    )
    registry = MetricRegistry((spec,))

    def calculate_return_1d(context: MetricContext, metric_spec: MetricSpec) -> pl.DataFrame:
        return pl.DataFrame({"unexpected": [1.2]})

    engine = MetricEngine(registry=registry, calculators={"return_1d": calculate_return_1d})

    with pytest.raises(ValueError, match="return_1d 缺少字段: value"):
        engine.compute(["return_1d"], context=MetricContext())
