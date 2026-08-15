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


def test_default_registry_contains_volatility_metrics() -> None:
    registry = create_default_registry()

    assert {
        "realized_volatility_20d",
        "downside_volatility_20d",
        "max_drawdown_60d",
    }.issubset(registry.specs)


def test_engine_computes_volatility_and_drawdown_metrics() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(61)]
    bars = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 61,
            "close": [100.0 + index for index in range(61)],
        }
    )
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": bars})))

    results = MetricEngine().compute(
        ["realized_volatility_20d", "downside_volatility_20d", "max_drawdown_60d"],
        context=context,
    )

    assert results[0].frame["realized_volatility_20d"].drop_nulls().is_empty() is False
    assert results[1].frame["downside_volatility_20d"][-1] == pytest.approx(0.0)
    assert results[2].frame["max_drawdown_60d"][-1] == pytest.approx(0.0)
