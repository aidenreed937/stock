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


def _bars(days: int) -> pl.DataFrame:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(days)]
    return pl.DataFrame(
        {
            "trade_date": [day for day in dates for _ in range(3)],
            "symbol": ["AAA", "BBB", "CCC"] * days,
            "close": [
                value for index in range(days) for value in (100.0 + index, 400.0 - index, 50.0)
            ],
        }
    )


def test_default_registry_contains_breadth_metrics() -> None:
    registry = create_default_registry()

    assert {
        "advance_decline_ratio",
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "above_ma120_share",
        "new_high_share_252d",
        "new_low_share_252d",
    }.issubset(registry.specs)


def test_engine_computes_market_breadth_metrics() -> None:
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": _bars(121)})))

    results = MetricEngine().compute(
        ["advance_decline_ratio", "advance_share", "above_ma60_share"],
        context=context,
    )

    assert results[0].frame["advance_decline_ratio"][-1] == pytest.approx(1.0)
    assert results[1].frame["advance_share"][-1] == pytest.approx(1.0 / 3.0)
    assert results[2].frame["above_ma60_share"][-1] == pytest.approx(1.0 / 3.0)


def test_engine_computes_new_high_and_low_shares() -> None:
    context = MetricContext(catalog=cast("object", FakeCatalog({"stock_daily_bar": _bars(253)})))

    results = MetricEngine().compute(
        ["new_high_share_252d", "new_low_share_252d"],
        context=context,
    )

    assert results[0].frame["new_high_share_252d"][-1] == pytest.approx(2.0 / 3.0)
    assert results[1].frame["new_low_share_252d"][-1] == pytest.approx(2.0 / 3.0)
