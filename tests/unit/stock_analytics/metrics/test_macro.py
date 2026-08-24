from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock_analytics.metrics.spec import EntityType, MetricDomain


class FakeCatalog:
    storage_dir = Path("data/curated")

    def __init__(self, datasets: dict[str, pl.DataFrame], data_source: str = "tushare") -> None:
        self.datasets = datasets
        self.data_source = data_source

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: object = None,
        end_date: object = None,
    ) -> pl.DataFrame:
        return self.datasets.get(dataset, pl.DataFrame())


def _lixinger_context() -> MetricContext:
    dates = [date(2026, 1, 5) + timedelta(days=index) for index in range(3)]
    national_debt = pl.DataFrame(
        {
            "trade_date": dates,
            "tcm_y2": [1.5, 1.8, 2.0],
            "tcm_y10": [2.5, 2.6, 2.7],
            "tcm_y30": [3.0, 3.1, 3.2],
        }
    )
    catalog = FakeCatalog({"national_debt": national_debt}, data_source="lixinger")
    return MetricContext(catalog=cast("object", catalog), end_date=dates[-1])


def _tushare_context() -> MetricContext:
    dates = [date(2025, 12, 1), date(2026, 1, 5)]
    daily_basic = pl.DataFrame(
        {
            "trade_date": [dates[0], dates[0], dates[1], dates[1]],
            "total_mv": [600.0e8, 400.0e8, 600.0e8, 400.0e8],
        }
    )
    cn_gdp = pl.DataFrame(
        {
            "quarter": [
                "2024Q1",
                "2024Q2",
                "2024Q3",
                "2024Q4",
                "2025Q1",
                "2025Q2",
                "2025Q3",
                "2025Q4",
            ],
            "gdp": [4000.0, 8200.0, 12600.0, 17200.0, 4500.0, 9200.0, 14100.0, 19200.0],
        }
    )
    catalog = FakeCatalog(
        {"daily_basic": daily_basic, "cn_gdp": cn_gdp},
        data_source="tushare",
    )
    return MetricContext(catalog=cast("object", catalog), end_date=dates[-1])


def test_default_registry_contains_macro_metrics() -> None:
    registry = create_default_registry()

    specs = [
        registry.get("yield_curve_slope_10y_2y"),
        registry.get("yield_curve_slope_30y_10y"),
        registry.get("buffett_securitization_ratio"),
    ]
    assert all(spec.domain == MetricDomain.MACRO for spec in specs)
    assert all(spec.entity_type == EntityType.MARKET for spec in specs)
    assert specs[0].required_datasets == ("national_debt",)
    assert specs[2].required_datasets == ("daily_basic", "cn_gdp")


def test_engine_computes_yield_curve_slopes() -> None:
    results = MetricEngine().compute(
        ["yield_curve_slope_10y_2y", "yield_curve_slope_30y_10y"],
        context=_lixinger_context(),
    )

    assert results[0].frame["yield_curve_slope_10y_2y"].to_list() == pytest.approx([1.0, 0.8, 0.7])
    assert results[1].frame["yield_curve_slope_30y_10y"].to_list() == pytest.approx([0.5, 0.5, 0.5])


def test_yield_curve_missing_30y_column_keeps_10y_2y() -> None:
    dates = [date(2026, 1, 5), date(2026, 1, 6)]
    national_debt = pl.DataFrame({"trade_date": dates, "tcm_y2": [1.5, 1.8], "tcm_y10": [2.5, 2.6]})
    catalog = FakeCatalog({"national_debt": national_debt}, data_source="lixinger")
    context = MetricContext(catalog=cast("object", catalog), end_date=dates[-1])

    results = MetricEngine().compute(
        ["yield_curve_slope_10y_2y", "yield_curve_slope_30y_10y"],
        context=context,
    )

    assert results[0].frame["yield_curve_slope_10y_2y"].to_list() == pytest.approx([1.0, 0.8])
    assert results[1].frame.columns == ["trade_date", "yield_curve_slope_30y_10y"]
    assert results[1].frame.is_empty()


def test_engine_computes_buffett_securitization_ratio() -> None:
    results = MetricEngine().compute(
        ["buffett_securitization_ratio"],
        context=_tushare_context(),
    )

    frame = results[0].frame
    assert frame["buffett_securitization_ratio"].to_list() == pytest.approx(
        [1000.0 / 18700.0 * 100.0, 1000.0 / 19200.0 * 100.0],
        rel=1e-9,
    )


def test_buffett_ratio_returns_empty_when_gdp_missing() -> None:
    dates = [date(2025, 12, 1)]
    daily_basic = pl.DataFrame({"trade_date": dates, "total_mv": [1000.0e8]})
    catalog = FakeCatalog({"daily_basic": daily_basic}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=dates[-1])

    results = MetricEngine().compute(["buffett_securitization_ratio"], context=context)

    assert results[0].frame.columns == ["trade_date", "buffett_securitization_ratio"]
    assert results[0].frame.is_empty()


def test_buffett_ratio_is_null_when_gdp_history_too_short() -> None:
    dates = [date(2025, 12, 1)]
    daily_basic = pl.DataFrame({"trade_date": dates, "total_mv": [1000.0e8]})
    cn_gdp = pl.DataFrame({"quarter": ["2025Q3", "2025Q4"], "gdp": [14100.0, 19200.0]})
    catalog = FakeCatalog({"daily_basic": daily_basic, "cn_gdp": cn_gdp}, data_source="tushare")
    context = MetricContext(catalog=cast("object", catalog), end_date=dates[-1])

    results = MetricEngine().compute(["buffett_securitization_ratio"], context=context)

    frame = results[0].frame
    assert len(frame) == 1
    assert frame["buffett_securitization_ratio"].null_count() == 1


def test_macro_metric_honors_start_date() -> None:
    context = _lixinger_context()
    context.start_date = context.end_date

    results = MetricEngine().compute(["yield_curve_slope_10y_2y"], context=context)

    assert results[0].frame["trade_date"].to_list() == [date(2026, 1, 7)]
    assert results[0].frame["yield_curve_slope_10y_2y"].to_list() == pytest.approx([0.7])


def test_yield_curve_metric_empty_when_no_national_debt() -> None:
    catalog = FakeCatalog({}, data_source="lixinger")
    context = MetricContext(catalog=cast("object", catalog), end_date=date(2026, 1, 7))

    results = MetricEngine().compute(["yield_curve_slope_10y_2y"], context=context)

    assert results[0].frame.columns == ["trade_date", "yield_curve_slope_10y_2y"]
    assert results[0].frame.is_empty()
