"""市场温度计事实采集辅助函数测试。"""

from datetime import date

import polars as pl

from stock.analytics.market_temperature.config import DatasetConfig
from stock.analytics.market_temperature.facts import _latest_dataset_date, _parse_date_value


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
