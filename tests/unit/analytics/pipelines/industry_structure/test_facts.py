"""行业结构事实采集辅助函数测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.industry_structure.facts import _latest_dataset_date
from stock_reporting.interpretation.industry_structure.config import DatasetConfig


class _FakeCatalog:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame
        self.end_date: date | None = None

    def load_dataset(self, dataset: str, *, end_date: date | None = None) -> pl.DataFrame:
        self.end_date = end_date
        return self.frame


def test_latest_dataset_date_is_clamped_to_as_of_date_for_trade_date() -> None:
    catalog = _FakeCatalog(pl.DataFrame({"trade_date": [date(2026, 6, 30), date(2026, 8, 14)]}))
    item = DatasetConfig(data_source="tushare", dataset="sw_daily")

    latest = _latest_dataset_date(catalog, item, date(2026, 6, 30))  # type: ignore[arg-type]

    assert latest == date(2026, 6, 30)
    assert catalog.end_date == date(2026, 6, 30)


def test_latest_dataset_date_is_clamped_to_as_of_date_for_configured_date_column() -> None:
    catalog = _FakeCatalog(pl.DataFrame({"ann_date": ["20260630", "20260814"]}))
    item = DatasetConfig(data_source="tushare", dataset="forecast", date_column="ann_date")

    latest = _latest_dataset_date(catalog, item, date(2026, 6, 30))  # type: ignore[arg-type]

    assert latest == date(2026, 6, 30)
