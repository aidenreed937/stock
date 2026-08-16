from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock.analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock.analytics.metrics.calculators.liquidity import _rolling_percentile


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


def test_default_registry_contains_liquidity_metrics() -> None:
    registry = create_default_registry()

    assert {
        "market_turnover_rate",
        "turnover_rate_percentile_1250d",
        "turnover_rate_zscore_60d",
        "amount_ma_ratio_20d",
        "amount_zscore_60d",
    }.issubset(registry.specs)


def test_engine_computes_liquidity_metrics() -> None:
    dates = [date(2022, 1, 1) + timedelta(days=index) for index in range(1251)]
    daily_basic = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 1251,
            "turnover_rate": [1.0 + index for index in range(1251)],
        }
    )
    bars = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["AAA"] * 1251,
            "amount": [100.0 + index for index in range(1251)],
        }
    )
    context = MetricContext(
        catalog=cast(
            "object",
            FakeCatalog({"daily_basic": daily_basic, "stock_daily_bar": bars}),
        )
    )

    results = MetricEngine().compute(
        [
            "market_turnover_rate",
            "turnover_rate_percentile_1250d",
            "amount_ma_ratio_20d",
        ],
        context=context,
    )

    assert results[0].frame["market_turnover_rate"][-1] == pytest.approx(1251.0)
    assert results[1].frame["turnover_rate_percentile_1250d"][-1] == pytest.approx(100.0)
    assert results[2].frame["amount_ma_ratio_20d"][-1] == pytest.approx(1350.0 / 1340.5)


def test_rolling_percentile_ignores_historical_nulls_when_current_value_exists() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, None, 3.0, 4.0, None]}).with_columns(
        _rolling_percentile("value", "value_percentile_5d", 5)
    )

    assert frame["value_percentile_5d"][4] == pytest.approx(100.0)
    assert frame["value_percentile_5d"][5] is None
