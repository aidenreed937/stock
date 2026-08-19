"""实时基准与监控计算测试。"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

import polars as pl

from stock_analytics.realtime.monitor import RealtimeMonitor, build_realtime_baselines
from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import BaseRealtimeFetcher, RealtimeQuote


class _Catalog:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame

    def load_bars(self, symbols: list[str], **_: object) -> pl.DataFrame:
        return self.frame.filter(pl.col("symbol").is_in(symbols))


class _Fetcher(BaseRealtimeFetcher):
    source = "tencent"

    def __init__(self, quote: RealtimeQuote, *, fail: bool = False) -> None:
        self.quote = quote
        self.fail = fail

    def fetch_quotes(self, symbols: Sequence[str]) -> tuple[RealtimeQuote, ...]:
        if self.fail:
            raise DataFetchError("network down")
        return tuple(self.quote.model_copy(update={"symbol": symbol}) for symbol in symbols)


def _history() -> pl.DataFrame:
    start = date(2026, 5, 1)
    rows = []
    for index in range(60):
        close = 100.0 + index
        rows.append(
            {
                "symbol": "600519.SH",
                "trade_date": start + timedelta(days=index),
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "amount": 1000.0,
            }
        )
    return pl.DataFrame(rows)


def test_build_baseline_uses_latest_completed_day_and_rolling_values() -> None:
    frame = _history()
    catalog = _Catalog(frame)

    baselines = build_realtime_baselines(
        catalog, {"stock_daily_bar": ["600519.SH"]}, as_of_date=date(2026, 8, 19)
    )

    baseline = baselines["600519.SH"]
    assert baseline.baseline_trade_date == date(2026, 6, 29)
    assert baseline.yesterday_close == 159.0
    assert baseline.ma20 == 149.5
    assert baseline.ma60 == 129.5
    assert baseline.avg_amount_20d == 1000.0
    assert baseline.status == "available"


def test_monitor_calculates_deviation_volume_ratio_and_breakout() -> None:
    now = datetime(2026, 8, 19, 10, 0, 0)
    quote = RealtimeQuote(
        symbol="600519.SH",
        provider_symbol="sh600519",
        received_at=now,
        quote_at=now,
        price=200.0,
        pre_close=159.0,
        amount=2000.0,
    )
    monitor = RealtimeMonitor(
        _Fetcher(quote),
        _Catalog(_history()),
    )

    result = monitor.run(
        {"stock_daily_bar": ["600519.SH"]},
        as_of_date=date(2026, 8, 19),
        now=now,
    )
    row = result.row(0, named=True)

    assert row["baseline_status"] == "available"
    assert row["ma20_deviation_pct"] == 33.77926421404682
    assert row["amount_ratio_20d"] == 2.0
    assert row["breakout_20d"] is True
    assert row["stop_loss_60d"] is False
    assert "BREAKOUT_20D" in row["warning"]


def test_monitor_marks_cached_quote_expired_and_suppresses_metrics() -> None:
    received_at = datetime(2026, 8, 19, 10, 0, 0)
    quote = RealtimeQuote(
        symbol="600519.SH",
        provider_symbol="sh600519",
        received_at=received_at,
        quote_at=received_at,
        price=200.0,
        pre_close=159.0,
        amount=2000.0,
    )
    monitor = RealtimeMonitor(
        _Fetcher(quote, fail=False),
        _Catalog(_history()),
    )
    monitor.run({"stock_daily_bar": ["600519.SH"]}, now=received_at)
    monitor.fetcher = _Fetcher(quote, fail=True)

    result = monitor.run(
        {"stock_daily_bar": ["600519.SH"]},
        as_of_date=date(2026, 8, 19),
        now=received_at + timedelta(seconds=61),
    )
    row = result.row(0, named=True)

    assert row["freshness"] == "expired"
    assert row["price"] is None
    assert "QUOTE_EXPIRED" in row["warning"]


def test_monitor_marks_suspicious_amount_ratio_without_rescaling() -> None:
    now = datetime(2026, 8, 19, 10, 0, 0)
    quote = RealtimeQuote(
        symbol="600519.SH",
        provider_symbol="sh600519",
        received_at=now,
        quote_at=now,
        price=200.0,
        pre_close=159.0,
        amount=2000.0,
    )
    monitor = RealtimeMonitor(
        _Fetcher(quote),
        _Catalog(_history()),
        max_amount_ratio=1.0,
    )

    row = monitor.run(
        {"stock_daily_bar": ["600519.SH"]},
        as_of_date=date(2026, 8, 19),
        now=now,
    ).row(0, named=True)

    assert row["amount_ratio_20d"] is None
    assert row["realtime_amount"] == 2000.0
    assert "AMOUNT_UNIT_SUSPECT" in row["warning"]


def test_monitor_suppresses_metrics_when_quote_date_crosses_midnight() -> None:
    received_at = datetime(2026, 8, 20, 0, 1, 0)
    quote = RealtimeQuote(
        symbol="600519.SH",
        provider_symbol="sh600519",
        received_at=received_at,
        quote_at=received_at - timedelta(minutes=2),
        price=200.0,
        pre_close=159.0,
        amount=2000.0,
    )
    monitor = RealtimeMonitor(
        _Fetcher(quote),
        _Catalog(_history()),
    )

    row = monitor.run(
        {"stock_daily_bar": ["600519.SH"]},
        as_of_date=date(2026, 8, 20),
        now=received_at,
    ).row(0, named=True)

    assert row["freshness"] == "missing"
    assert row["price"] is None
    assert row["amount_ratio_20d"] is None
