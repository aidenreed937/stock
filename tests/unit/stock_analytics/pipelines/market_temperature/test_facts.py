"""市场温度计事实采集辅助函数测试。"""

from datetime import date
from pathlib import Path

import polars as pl

import stock_analytics.pipelines.market_temperature.facts as facts_module
from stock_analytics.features.builders.market_daily import MarketDailyBuilder
from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.facts import (
    _latest_dataset_date,
    _parse_date_value,
    collect_facts,
)
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.market_temperature.config import (
    DatasetConfig,
    MarketTemperatureConfig,
)


class _FakeCatalog:
    def __init__(self, frame: pl.DataFrame, latest_dates: list[date] | None = None) -> None:
        self.frame = frame
        self.latest_dates = latest_dates or []
        self.start_date: date | None = None
        self.end_date: date | None = None

    def latest_trade_dates(self, dataset: str, *, n: int = 1) -> list[date]:
        return self.latest_dates[:n]

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        self.start_date = start_date
        self.end_date = end_date
        return self.frame


def test_parse_date_value_supports_compact_month() -> None:
    assert _parse_date_value("202606") == date(2026, 6, 1)


def test_parse_date_value_supports_compact_day() -> None:
    assert _parse_date_value("20260814") == date(2026, 8, 14)


def test_latest_dataset_date_is_clamped_to_as_of_date_for_trade_date() -> None:
    catalog = _FakeCatalog(pl.DataFrame({"trade_date": [date(2026, 6, 30), date(2026, 8, 14)]}))
    item = DatasetConfig(data_source="tushare", dataset="daily_basic", dimension="valuation")

    latest = _latest_dataset_date(catalog, item, date(2026, 6, 30))  # type: ignore[arg-type]

    assert latest == date(2026, 6, 30)
    assert catalog.end_date == date(2026, 6, 30)


def test_latest_dataset_date_is_clamped_to_as_of_date_for_configured_date_column() -> None:
    catalog = _FakeCatalog(pl.DataFrame({"month": ["202606", "202608"]}))
    item = DatasetConfig(
        data_source="tushare",
        dataset="cn_m",
        dimension="macro_liquidity",
        date_column="month",
    )

    latest = _latest_dataset_date(catalog, item, date(2026, 6, 30))  # type: ignore[arg-type]

    assert latest == date(2026, 6, 1)


def test_latest_dataset_date_uses_catalog_watermark_without_loading_full_dataset() -> None:
    catalog = _FakeCatalog(
        pl.DataFrame({"trade_date": [date(2026, 8, 14)]}),
        latest_dates=[date(2026, 8, 14)],
    )
    item = DatasetConfig(data_source="tushare", dataset="stock_daily_bar", dimension="meta")

    latest = _latest_dataset_date(catalog, item, date(2026, 8, 14))  # type: ignore[arg-type]

    assert latest == date(2026, 8, 14)
    assert catalog.start_date is None
    assert catalog.end_date is None


def test_latest_dataset_date_limits_historical_watermark_lookup_window() -> None:
    catalog = _FakeCatalog(
        pl.DataFrame({"trade_date": [date(2026, 6, 30)]}),
        latest_dates=[date(2026, 8, 14)],
    )
    item = DatasetConfig(data_source="tushare", dataset="daily_basic", dimension="valuation")

    latest = _latest_dataset_date(catalog, item, date(2026, 6, 30))  # type: ignore[arg-type]

    assert latest == date(2026, 6, 30)
    assert catalog.start_date == date(2026, 6, 16)
    assert catalog.end_date == date(2026, 6, 30)


def test_collect_facts_emits_one_short_term_fact_per_window(
    tmp_path: Path, monkeypatch: object
) -> None:
    storage_dir = tmp_path / "curated"
    trade_dates = tuple(date(2026, 8, day) for day in range(1, 11))
    partition = storage_dir / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    partition.mkdir(parents=True)
    rows = []
    for index, trade_date in enumerate(trade_dates):
        rows.extend(
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": trade_date,
                    "close": 10.0 + index * 0.1,
                    "amount": 100_000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
                {
                    "symbol": "000002.SZ",
                    "trade_date": trade_date,
                    "close": 20.0 - index * 0.05,
                    "amount": 200_000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
            ]
        )
    pl.DataFrame(rows).write_parquet(partition / "data.parquet")

    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    store = FeatureStore(mart_dir=storage_dir / "mart")
    MarketDailyBuilder(catalog=catalog, store=store).build(
        start_date=trade_dates[0], end_date=trade_dates[-1], save=True
    )

    monkeypatch.setattr(facts_module, "collect_derived_metric_rows", lambda **_: [])
    config = MarketTemperatureConfig.from_mapping(
        {
            "main_window": 10,
            "short_windows": [5, 10],
            "metric_values": {"enabled": True},
            "dimensions": [],
            "datasets": [],
        }
    )

    facts = collect_facts(
        config,
        as_of_date=trade_dates[-1],
        trade_dates=trade_dates,
        storage_dir=storage_dir,
    )
    short_term = facts.filter(pl.col("dimension") == "short_term")

    assert set(short_term["metric_id"].to_list()) == {
        "short_term_temperature_5d",
        "short_term_temperature_10d",
    }
    assert short_term.height == 2
    assert short_term["metric_id"].n_unique() == 2
    assert short_term["fact_id"].n_unique() == 2
