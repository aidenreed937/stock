"""市场温度批次数据缓存测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.market_temperature.cache import CachedCatalog, DatasetFrameCache


class _Catalog:
    data_source = "tushare"

    def __init__(self) -> None:
        self.calls: list[tuple[date | None, date | None, tuple[str, ...] | None]] = []
        self.watermark_calls: list[tuple[str, int, str | None]] = []
        self.frame = pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)],
                "value": [1.0, 2.0, 3.0],
                "extra": [10.0, 20.0, 30.0],
            }
        )

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
    ) -> pl.DataFrame:
        del dataset
        self.calls.append((start_date, end_date, tuple(columns) if columns else None))
        frame = self.frame
        if start_date is not None:
            frame = frame.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            frame = frame.filter(pl.col("trade_date") <= end_date)
        if columns is not None:
            frame = frame.select([column for column in columns if column in frame.columns])
        return frame

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        *,
        n: int = 1,
        date_column: str | None = None,
        **_: object,
    ) -> list[date]:
        self.watermark_calls.append((dataset, n, date_column))
        return [date(2026, 8, 3), date(2026, 8, 2), date(2026, 8, 1)][:n]


def test_cache_reuses_batch_superset_and_slices_dates() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    first = cache.load(
        catalog,
        "demo",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
        columns=["trade_date", "value"],
    )
    second = cache.load(
        catalog,
        "demo",
        start_date=date(2026, 8, 2),
        end_date=date(2026, 8, 2),
        columns=["trade_date", "value"],
    )

    assert first["value"].to_list() == [1.0]
    assert second["value"].to_list() == [2.0]
    assert len(catalog.calls) == 1
    assert catalog.calls[0][1] == date(2026, 8, 3)


def test_cache_expands_projected_columns_once() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    cache.load(catalog, "demo", columns=["trade_date", "value"])
    result = cache.load(catalog, "demo", columns=["trade_date", "value", "extra"])
    narrow_again = cache.load(catalog, "demo", columns=["trade_date", "value"])

    assert result.columns == ["trade_date", "value", "extra"]
    assert narrow_again.columns == ["trade_date", "value"]
    assert len(catalog.calls) == 2
    assert set(catalog.calls[-1][2] or ()) == {"trade_date", "value", "extra"}


def test_cache_reuses_wider_projection_for_narrower_request() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    cache.load(catalog, "demo", columns=["trade_date", "value", "extra"])
    result = cache.load(catalog, "demo", columns=["trade_date", "value"])

    assert result.columns == ["trade_date", "value"]
    assert len(catalog.calls) == 1


def test_cache_date_slice_never_exposes_batch_future() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    result = cache.load(
        catalog,
        "demo",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        columns=["trade_date", "value"],
    )

    assert result["trade_date"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]


def test_cache_reuses_batch_watermark_scan() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    assert cache.latest_trade_dates(catalog, "demo", n=3) == (
        date(2026, 8, 3),
        date(2026, 8, 2),
        date(2026, 8, 1),
    )
    assert cache.latest_trade_dates(catalog, "demo", n=1) == (date(2026, 8, 3),)
    assert catalog.watermark_calls == [("demo", 3, None)]


def test_cache_remembers_missing_watermark() -> None:
    catalog = _Catalog()
    cache = DatasetFrameCache()

    catalog.latest_trade_dates = lambda **_: []  # type: ignore[method-assign]
    assert cache.latest_trade_dates(catalog, "missing") == ()
    assert cache.latest_trade_dates(catalog, "missing") == ()


def test_cache_isolates_data_sources() -> None:
    tushare = _Catalog()
    yfinance = _Catalog()
    yfinance.data_source = "yfinance"
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))

    cache.load(tushare, "demo", columns=["trade_date", "value"])
    cache.load(yfinance, "demo", columns=["trade_date", "value"])

    assert len(tushare.calls) == 1
    assert len(yfinance.calls) == 1
    assert cache.dataset_count == 2


def test_cached_catalog_bypasses_frame_cache_for_symbol_filters() -> None:
    class _FilteredCatalog:
        data_source = "tushare"

        def __init__(self) -> None:
            self.calls: list[list[str] | None] = []

        def load_dataset(
            self,
            dataset: str,
            *,
            symbols: list[str] | None = None,
            **_: object,
        ) -> pl.DataFrame:
            del dataset
            self.calls.append(symbols)
            return pl.DataFrame(
                {
                    "symbol": symbols or ["AAA"],
                    "trade_date": [date(2026, 8, 3)] * len(symbols or ["AAA"]),
                }
            )

    catalog = _FilteredCatalog()
    cache = DatasetFrameCache(end_date=date(2026, 8, 3))
    cached_catalog = CachedCatalog(catalog, cache)  # type: ignore[arg-type]

    first = cached_catalog.load_dataset("demo", symbols=["AAA"])
    second = cached_catalog.load_dataset("demo", symbols=["BBB"])

    assert first["symbol"].to_list() == ["AAA"]
    assert second["symbol"].to_list() == ["BBB"]
    assert catalog.calls == [["AAA"], ["BBB"]]
    assert cache.dataset_count == 0
