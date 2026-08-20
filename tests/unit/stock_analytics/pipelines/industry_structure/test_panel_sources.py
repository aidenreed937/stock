"""行业结构面板数据源映射测试。"""

from datetime import date, timedelta

import polars as pl
import pytest

from stock_analytics.pipelines.industry_structure.panel_sources import (
    _stock_industry_map_from_index_member,
    load_benchmark_return_20d,
    load_stock_industry_map,
)


class _MemoryCatalog:
    def __init__(
        self,
        datasets: dict[str, pl.DataFrame],
        latest_dates: list[date] | None = None,
    ) -> None:
        self.datasets = datasets
        self.latest_dates = latest_dates or []
        self.symbol_requests: list[list[str] | None] = []

    def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
        frame = self.datasets.get(dataset, pl.DataFrame())
        symbols = kwargs.get("symbols")
        self.symbol_requests.append(symbols if isinstance(symbols, list) else None)
        if isinstance(symbols, list) and "symbol" in frame.columns:
            return frame.filter(pl.col("symbol").is_in(symbols))
        return frame

    def latest_trade_dates(
        self, dataset: str = "stock_daily_bar", n: int = 1, **_: object
    ) -> list[date]:
        return self.latest_dates[:n]


def test_index_member_date_filter_uses_date_semantics() -> None:
    catalog = _MemoryCatalog(
        {
            "index_member": pl.DataFrame(
                {
                    "index_code": ["801001.SI"] * 4,
                    "con_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
                    "in_date": [
                        date(2020, 1, 1),
                        date(2024, 11, 1),
                        date(2020, 1, 1),
                        date(2020, 1, 1),
                    ],
                    "out_date": [
                        date(2025, 1, 1),
                        None,
                        date(2024, 10, 30),
                        None,
                    ],
                }
            )
        }
    )

    result = _stock_industry_map_from_index_member(
        catalog,
        date(2024, 10, 31),
        {"801001.SI": "801001.SI"},
    )

    assert set(result["stock_key"].to_list()) == {"000001", "000004"}


def test_benchmark_return_resolves_csi_suffix() -> None:
    trade_dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(22)]
    catalog = _MemoryCatalog(
        {
            "index_daily": pl.DataFrame(
                {
                    "symbol": ["000985.CSI"] * 22,
                    "trade_date": trade_dates,
                    "close": [99.0, *[100.0 + index * 0.5 for index in range(21)]],
                }
            )
        }
    )

    result = load_benchmark_return_20d(catalog, "000985", trade_dates[-1])

    assert result == pytest.approx(10.0)
    assert catalog.symbol_requests == [["000985"], ["000985.CSI"]]


def test_historical_mapping_does_not_use_date_free_static_constituents() -> None:
    index_classify = pl.DataFrame(
        {
            "index_code": ["801001.SI"],
            "industry_code": ["270000"],
            "level": ["L1"],
            "src": ["SW2021"],
        }
    )
    index_member = pl.DataFrame(
        {
            "index_code": ["801001.SI"],
            "con_code": ["000001.SZ"],
            "in_date": [date(2020, 1, 1)],
            "out_date": [None],
        }
    )
    static_constituents = pl.DataFrame(
        {
            "symbol": ["000002.SZ"],
            "industryCode": ["270000"],
        }
    )
    tushare = _MemoryCatalog(
        {
            "index_classify": index_classify,
            "index_member": index_member,
        },
        latest_dates=[date(2026, 8, 14)],
    )
    lixinger = _MemoryCatalog({"sw_2021_constituents": static_constituents})

    historical = load_stock_industry_map(
        tushare,
        lixinger,
        _config(),
        date(2026, 8, 13),
    )
    current = load_stock_industry_map(
        tushare,
        lixinger,
        _config(),
        date(2026, 8, 14),
    )

    assert historical["stock_key"].to_list() == ["000001"]
    assert set(current["stock_key"].to_list()) == {"000001", "000002"}


def _config():
    from stock_reporting.interpretation.industry_structure.config import (
        FundamentalBlendConfig,
        IndustryStructureConfig,
        ScoreWeights,
    )

    return IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root="data/analytics/industry_structure",
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="SW2021",
        benchmark="000985.CSI",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )
