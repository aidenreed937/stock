"""个股排雷数据源加载测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.sources import (
    load_stock_screen_sources,
    resolve_as_of_date,
)
from stock_reporting.interpretation.stock_screen.config import StockScreenConfig


class _Catalog:
    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self.frames = frames

    def latest_trade_dates(self, dataset: str, n: int = 1):
        return [date(2026, 8, 20) if dataset == "stock_daily_bar" else date(2026, 8, 19)][:n]

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        return self.frames.get(dataset, pl.DataFrame())


def test_resolve_as_of_uses_daily_dataset_intersection() -> None:
    catalog = _Catalog({})

    assert resolve_as_of_date(catalog=catalog) == date(2026, 8, 19)


def test_sources_clip_non_static_frames_at_as_of_date() -> None:
    config = StockScreenConfig.from_mapping(
        {
            "hard_exclusion": {"rules": []},
            "yellow_warn": {"rules": []},
            "datasets": [
                {"data_source": "tushare", "dataset": "stock_basic", "static": True},
                {"data_source": "tushare", "dataset": "daily_basic"},
            ],
        }
    )
    catalog = _Catalog(
        {
            "stock_basic": pl.DataFrame(
                {"ts_code": ["000001.SZ"], "name": ["测试公司"], "list_date": ["20200101"]}
            ),
            "daily_basic": pl.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "trade_date": ["20260820", "20260821"],
                    "close": [10.0, 11.0],
                }
            ),
        }
    )

    sources = load_stock_screen_sources(config, date(2026, 8, 20), catalogs={"tushare": catalog})

    assert sources.get("stock_basic")["symbol"].to_list() == ["000001.SZ"]
    assert sources.get("daily_basic")["trade_date"].to_list() == [date(2026, 8, 20)]
