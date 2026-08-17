from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl

from stock_analytics.metrics import MetricContext
from stock_analytics.metrics.datasets import build_calendar_lookback_window
from stock_analytics.metrics.datasets.loaders import load_metric_dataset

if TYPE_CHECKING:
    from stock_data.catalog import DataCatalog


class FakeCatalog:
    def __init__(self, data_source: str = "tushare", storage_dir: Path | None = None) -> None:
        self.data_source = data_source
        self.storage_dir = storage_dir or Path("data/curated")
        self.calls: list[tuple[str, str]] = []

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: object = None,
        end_date: object = None,
    ) -> pl.DataFrame:
        self.calls.append((self.data_source, dataset))
        return pl.DataFrame({"data_source": [self.data_source], "dataset": [dataset]})


def test_load_metric_dataset_uses_actual_data_source_cache_key() -> None:
    catalog = FakeCatalog(data_source="tushare")
    context = MetricContext(catalog=cast("DataCatalog", catalog))

    first = load_metric_dataset(context, "stock_daily_bar")
    second = load_metric_dataset(context, "stock_daily_bar", data_source="tushare")

    assert first.equals(second)
    assert catalog.calls == [("tushare", "stock_daily_bar")]
    assert list(context.cache) == ["tushare:stock_daily_bar:None:None"]


def test_build_calendar_lookback_window_semantics() -> None:
    end_date = date(2026, 8, 14)
    window = build_calendar_lookback_window(end_date, 7)
    assert window.start_date == end_date - timedelta(days=7)
    assert window.end_date == end_date
    assert window.lookback_days == 7
