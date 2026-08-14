from datetime import date
from unittest.mock import MagicMock
from types import SimpleNamespace
import pytest

from stock.data.backfill import (
    HistoricalBackfiller,
    _default_symbols_for_endpoint,
    _execute_parallel_tasks,
    _filter_supported_symbols,
    _load_backfill_yaml_config,
    _resolve_calendar_dates,
    _watchlist_symbols,
)
from stock.exceptions import DataFetchError


def test_watchlist_symbols_resolution() -> None:
    # 1. watchlist is None
    cfg_empty = SimpleNamespace(watchlists=SimpleNamespace())
    assert _watchlist_symbols("unknown", "stock_daily_bar", cfg_empty, set()) == []

    # 2. watchlist has indices for index endpoint
    cfg_indices = SimpleNamespace(
        watchlists=SimpleNamespace(tushare=SimpleNamespace(indices=["000300.SH"]))
    )
    assert _watchlist_symbols(
        "tushare", "index_daily", cfg_indices, {"index_daily"}
    ) == ["000300.SH"]

    # 3. watchlist has all_symbols
    cfg_symbols = SimpleNamespace(
        watchlists=SimpleNamespace(tushare=SimpleNamespace(all_symbols=["600519.SH"]))
    )
    assert _watchlist_symbols("tushare", "stock_daily_bar", cfg_symbols, set()) == ["600519.SH"]


def test_filter_supported_symbols() -> None:
    cfg = SimpleNamespace(
        source_endpoint_supports={"tushare": {"daily": ["600519.SH", "000001.SZ"]}}
    )
    filtered = _filter_supported_symbols(
        ["600519.SH", "INVALID.SH", "000001.SZ"], "tushare", "daily", cfg
    )
    assert filtered == ["600519.SH", "000001.SZ"]


def test_resolve_calendar_dates_fallback() -> None:
    # 1. fetcher without fetch_trade_cal (natural days)
    fetcher_mock = MagicMock(spec=[])
    natural_days = _resolve_calendar_dates(
        fetcher_mock, "fred", date(2024, 1, 1), date(2024, 1, 3)
    )
    assert len(natural_days) == 3

    # 2. fetcher with fetch_trade_cal raising exception (weekday fallback)
    fetcher_err = MagicMock()
    fetcher_err.fetch_trade_cal.side_effect = Exception("network error")
    weekdays = _resolve_calendar_dates(
        fetcher_err, "tushare", date(2024, 1, 5), date(2024, 1, 8)
    )
    # 2024-01-05 (Fri), 2024-01-08 (Mon)
    assert weekdays == [date(2024, 1, 5), date(2024, 1, 8)]


def test_execute_parallel_tasks() -> None:
    def sync_fn(d: date) -> bool:
        return d != date(2024, 1, 2)

    items = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    synced, failed = _execute_parallel_tasks(
        task_fn=sync_fn, items=items, max_workers=2, item_desc=lambda d: str(d)
    )
    assert synced == 2
    assert failed == 1


def test_historical_backfiller_frequency_property() -> None:
    backfiller = HistoricalBackfiller(data_source="tushare", endpoint="cn_cpi")
    assert backfiller.frequency == "monthly"
