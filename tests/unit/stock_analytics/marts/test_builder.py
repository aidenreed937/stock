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

    def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
        columns = kwargs.get("columns")
        self.calls.append((dataset, columns if isinstance(columns, list) else None))
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
