from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock_analytics.primitives.rules import rolling_percentile


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
            "circ_mv": [100.0] * 1251,
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

    assert results[0].frame["market_turnover_rate"][-1] == pytest.approx(1350.0)
    assert results[1].frame["turnover_rate_percentile_1250d"][-1] == pytest.approx(100.0)
    assert results[2].frame["amount_ma_ratio_20d"][-1] == pytest.approx(1350.0 / 1340.5)


def test_market_turnover_is_scale_invariant_and_rejects_invalid_market_value() -> None:
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    base = {
        "daily_basic": pl.DataFrame({"trade_date": dates, "circ_mv": [1000.0, 2000.0]}),
        "stock_daily_bar": pl.DataFrame({"trade_date": dates, "amount": [100.0, 400.0]}),
    }
    scaled = {
        "daily_basic": base["daily_basic"].with_columns(
            (pl.col("circ_mv") * 1000.0).alias("circ_mv")
        ),
        "stock_daily_bar": base["stock_daily_bar"].with_columns(
            (pl.col("amount") * 1000.0).alias("amount")
        ),
    }

    base_result = MetricEngine().compute(
        ["market_turnover_rate"],
        context=MetricContext(catalog=cast("object", FakeCatalog(base))),
    )
    scaled_result = MetricEngine().compute(
        ["market_turnover_rate"],
        context=MetricContext(catalog=cast("object", FakeCatalog(scaled))),
    )

    assert scaled_result[0].frame["market_turnover_rate"].to_list() == pytest.approx(
        base_result[0].frame["market_turnover_rate"].to_list()
    )

    invalid_result = MetricEngine().compute(
        ["market_turnover_rate"],
        context=MetricContext(
            catalog=cast(
                "object",
                FakeCatalog(
                    {
                        "daily_basic": pl.DataFrame({"trade_date": dates, "circ_mv": [0.0, -1.0]}),
                        "stock_daily_bar": base["stock_daily_bar"],
                    }
                ),
            )
        ),
    )
    assert invalid_result[0].frame["market_turnover_rate"].to_list() == [None, None]


def test_rolling_percentile_ignores_historical_nulls_when_current_value_exists() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, None, 3.0, 4.0, None]}).with_columns(
        rolling_percentile("value", 5, "value_percentile_5d")
    )

    assert frame["value_percentile_5d"][4] == pytest.approx(100.0)
    assert frame["value_percentile_5d"][5] is None
