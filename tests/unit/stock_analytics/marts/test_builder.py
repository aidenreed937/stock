"""领域 Mart 构建器测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.marts.builder import DomainMartBuilder


class _CatalogStub:
    def __init__(self) -> None:
        self.storage_dir = Path(".")
        self.calls: list[tuple[str, list[str] | None]] = []
        self.date_ranges: list[tuple[str, date | None, date | None]] = []

    def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
        columns = kwargs.get("columns")
        self.calls.append((dataset, columns if isinstance(columns, list) else None))
        self.date_ranges.append(
            (
                dataset,
                kwargs.get("start_date") if isinstance(kwargs.get("start_date"), date) else None,
                kwargs.get("end_date") if isinstance(kwargs.get("end_date"), date) else None,
            )
        )
        if dataset == "fund_daily":
            return pl.DataFrame()
        if dataset == "index_daily_bar":
            return pl.DataFrame(
                {
                    "symbol": ["000300.SH"],
                    "trade_date": [date(2026, 8, 1)],
                    "close": [100.0],
                }
            )
        if dataset == "opt_daily":
            return pl.DataFrame(
                {
                    "symbol": ["C1"],
                    "trade_date": [date(2026, 8, 1)],
                    "settle": [10.0],
                }
            )
        if dataset == "opt_basic":
            return pl.DataFrame(
                {
                    "symbol": ["C1"],
                    "call_put": ["C"],
                    "exercise_price": [100.0],
                    "maturity_date": [date(2026, 9, 1)],
                    "opt_code": ["OP000300.SH"],
                    "opt_type": ["ETF期权"],
                }
            )
        return pl.DataFrame()

    def load_bars(self, **_: object) -> pl.DataFrame:
        return pl.DataFrame()


def test_builder_loads_index_underlying_for_index_option(tmp_path: Path, monkeypatch) -> None:
    catalog = _CatalogStub()
    store = FeatureStore(mart_dir=tmp_path / "mart")
    builder = DomainMartBuilder(catalog, store)
    monkeypatch.setattr(
        builder,
        "_load_risk_free_rates",
        lambda **_: pl.DataFrame({"trade_date": [date(2026, 8, 1)], "risk_free_rate": [0.02]}),
    )

    result = builder.build_settlement_iv_proxy(underlying_symbols=("000300.SH",))

    assert not result.is_empty()
    assert any(dataset == "index_daily_bar" for dataset, _ in catalog.calls)
    assert store.domain_mart_path("settlement_iv_proxy_daily").exists()


def test_builder_starts_iv_proxy_from_existing_mart_date(tmp_path: Path, monkeypatch) -> None:
    catalog = _CatalogStub()
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "settlement_iv_proxy_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1)],
                "underlying_symbol": ["000300.SH"],
                "settlement_iv_proxy_median": [0.2],
                "settlement_iv_proxy_call_median": [0.2],
                "settlement_iv_proxy_put_median": [0.2],
                "settlement_iv_proxy_put_call_skew": [0.0],
                "settlement_iv_proxy_valid_count": [2],
                "settlement_iv_proxy_call_count": [1],
                "settlement_iv_proxy_put_count": [1],
                "risk_free_rate": [0.02],
            }
        ),
        keys=["trade_date", "underlying_symbol"],
        date_column="trade_date",
        overwrite=True,
    )
    builder = DomainMartBuilder(catalog, store)
    monkeypatch.setattr(
        builder,
        "_load_risk_free_rates",
        lambda **_: pl.DataFrame({"trade_date": [date(2026, 8, 1)], "risk_free_rate": [0.02]}),
    )

    builder.build_settlement_iv_proxy(underlying_symbols=("000300.SH",))

    opt_start = next(start for dataset, start, _ in catalog.date_ranges if dataset == "opt_daily")
    assert opt_start == date(2026, 8, 1)
