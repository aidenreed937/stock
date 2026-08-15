from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock.analytics.metrics import MetricContext, MetricEngine, create_default_registry


class FakeCatalog:
    data_source = "tushare"
    storage_dir = Path("data/curated")

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self.datasets = datasets

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: object = None,
        end_date: object = None,
    ) -> pl.DataFrame:
        return self.datasets.get(dataset, pl.DataFrame())


def test_default_registry_contains_performance_metrics() -> None:
    registry = create_default_registry()

    assert {
        "return_1d",
        "return_5d",
        "return_20d",
        "return_60d",
        "return_252d",
    }.issubset(registry.specs)


def test_engine_computes_multi_window_returns() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(21)]
    bars = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 21,
            "close": [100.0 + index for index in range(21)],
        }
    )
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": bars})))

    results = MetricEngine().compute(["return_1d", "return_20d"], context=context)

    assert results[0].frame["return_1d"][-1] == pytest.approx(120.0 / 119.0 - 1.0)
    assert results[1].frame["return_20d"][-1] == pytest.approx(0.2)
