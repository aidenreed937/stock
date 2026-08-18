from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock_analytics.metrics.calculators import valuation


class FakeCatalog:
    data_source = "lixinger"
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


def _context() -> MetricContext:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(4)]
    index_fundamental = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["000300"] * 4,
            "pe_ttm.ew": [10.0, 30.0, 20.0, 40.0],
            "pb.ew": [4.0, 3.0, 2.0, 1.0],
            "dyr.ew": [0.01, 0.04, 0.02, 0.03],
        }
    )
    national_debt = pl.DataFrame(
        {
            "trade_date": dates[:3],
            "tcm_y10": [0.02, 0.02, 0.02],
        }
    )
    catalog = FakeCatalog({"index_fundamental": index_fundamental, "national_debt": national_debt})
    return MetricContext(catalog=cast("object", catalog), start_date=dates[2], end_date=dates[-1])


def test_default_registry_contains_valuation_metrics() -> None:
    registry = create_default_registry()

    assert {
        "earnings_yield",
        "pe_zscore_5y",
        "pb_zscore_5y",
        "pe_percentile_5y",
        "pb_percentile_5y",
        "dividend_yield_percentile_5y",
        "equity_risk_premium",
        "equity_risk_premium_percentile_5y",
        "equity_bond_yield_ratio",
        "dividend_bond_spread",
        "valuation_temperature",
    }.issubset(registry.specs)


def test_engine_computes_valuation_percentiles_and_zscore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(valuation, "_TRADING_DAYS_5Y", 3)

    results = MetricEngine().compute(
        ["earnings_yield", "pe_percentile_5y", "pb_percentile_5y", "pe_zscore_5y"],
        context=_context(),
    )

    assert results[0].frame["earnings_yield"].to_list() == [0.05, 0.025]
    assert results[1].frame["pe_percentile_5y"].to_list() == pytest.approx([50.0, 100.0])
    assert results[2].frame["pb_percentile_5y"].to_list() == pytest.approx([0.0, 0.0])
    assert results[3].frame["pe_zscore_5y"].null_count() == 0


def test_cross_source_metrics_use_latest_prior_bond_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(valuation, "_TRADING_DAYS_5Y", 3)

    results = MetricEngine().compute(
        [
            "equity_risk_premium",
            "equity_risk_premium_percentile_5y",
            "equity_bond_yield_ratio",
            "dividend_bond_spread",
            "valuation_temperature",
        ],
        context=_context(),
    )

    assert results[0].frame["equity_risk_premium"].to_list() == pytest.approx([0.03, 0.005])
    assert results[1].frame["equity_risk_premium_percentile_5y"].to_list() == pytest.approx(
        [50.0, 0.0]
    )
    assert results[2].frame["equity_bond_yield_ratio"].to_list() == pytest.approx([2.5, 1.25])
    assert results[3].frame["dividend_bond_spread"].to_list() == pytest.approx([0.0, 0.01])
    assert results[4].frame["valuation_temperature"].to_list() == pytest.approx([37.5, 62.5])
