from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry


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


def test_default_registry_contains_trend_metrics() -> None:
    registry = create_default_registry()

    assert {"ma_bias_20d", "rsi_14d", "distance_to_252d_high"}.issubset(registry.specs)


def test_engine_computes_ma_bias_and_rsi() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(21)]
    bars = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 21,
            "close": [100.0 + index for index in range(21)],
        }
    )
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": bars})))

    results = MetricEngine().compute(["ma_bias_20d", "rsi_14d"], context=context)

    assert results[0].frame["ma_bias_20d"][-1] == pytest.approx(120.0 / 110.5 - 1.0)
    assert results[1].frame["rsi_14d"][-1] > 99.0


def test_distance_to_252d_high_is_zero_on_new_high() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(253)]
    bars = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 253,
            "close": [100.0 + index for index in range(253)],
        }
    )
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": bars})))

    result = MetricEngine().compute(["distance_to_252d_high"], context=context)[0]

    assert result.frame["distance_to_252d_high"][-1] == pytest.approx(0.0)
