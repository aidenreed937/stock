"""市场温度计事实采集辅助函数测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.facts import (
    FACT_SCHEMA,
    _latest_dataset_date,
    _normalize_metric_dates,
    _parse_date_value,
    collect_facts,
    resolve_external_cutoff_date,
)
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


def test_resolve_external_cutoff_date_uses_previous_a_share_trade_date() -> None:
    trade_dates = (
        date(2026, 8, 14),
        date(2026, 8, 17),
        date(2026, 8, 18),
        date(2026, 8, 19),
    )

    assert resolve_external_cutoff_date(date(2026, 8, 18), trade_dates) == date(2026, 8, 17)
    assert resolve_external_cutoff_date(date(2026, 8, 19), trade_dates) == date(2026, 8, 18)
    assert resolve_external_cutoff_date(date(2026, 8, 17), trade_dates) == date(2026, 8, 14)
    assert resolve_external_cutoff_date(date(2026, 8, 13), trade_dates) == date(2026, 8, 12)


def test_metric_facts_have_uniform_metric_date_column() -> None:
    rows = _normalize_metric_dates(
        [
            {
                "category": "metric_value",
                "note": "source=mart.market_daily; metric_date=2026-08-13",
            },
            {
                "category": "metric_value",
                "note": "ann_window=2026-08-01..2026-08-14",
            },
            {"category": "data_watermark", "note": "metric_date=2026-08-13"},
        ]
    )
    frame = pl.DataFrame(rows, schema=FACT_SCHEMA)

    assert frame["metric_date"].dtype == pl.Date
    assert frame["metric_date"].to_list() == [
        date(2026, 8, 13),
        date(2026, 8, 14),
        None,
    ]


def test_collect_facts_emits_one_short_term_fact_per_window(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "curated"
    trade_dates = tuple(date(2026, 8, day) for day in range(1, 11))
    store = FeatureStore(mart_dir=storage_dir / "mart")
    store.save_market_temperature_derived_facts(
        pl.DataFrame(
            [
                {
                    "fact_id": f"short_term_temperature_{window}d",
                    "category": "metric_value",
                    "dimension": "short_term",
                    "data_source": "mart",
                    "dataset": "market_daily",
                    "as_of_date": trade_dates[-1],
                    "metric_date": trade_dates[-1],
                    "window": window,
                    "metric_id": f"short_term_temperature_{window}d",
                    "value_float": 50.0 + window,
                    "value_text": "",
                    "unit": "temperature",
                    "sample_size": window,
                    "source": "FeatureStore.market_daily",
                    "status": "ok",
                    "note": "预先物化短线事实",
                }
                for window in (5, 10)
            ],
            schema=FACT_SCHEMA,
        ),
        overwrite=True,
    )
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
