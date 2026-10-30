from datetime import date
from types import SimpleNamespace

from stock_data.pipeline import us_hybrid_backfill


def test_missing_by_symbol_uses_expected_sessions() -> None:
    sessions = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]

    missing = us_hybrid_backfill._missing_by_symbol(
        sessions,
        {"AAPL": {date(2026, 10, 1)}, "MSFT": set()},
        ["AAPL", "MSFT"],
    )

    assert missing == {
        "AAPL": {date(2026, 10, 2), date(2026, 10, 5)},
        "MSFT": set(sessions),
    }


def test_hybrid_skips_both_sources_when_yfinance_covers_range(monkeypatch) -> None:
    sessions = [date(2026, 10, 1), date(2026, 10, 2)]
    calls: list[object] = []
    monkeypatch.setattr(us_hybrid_backfill, "_sessions", lambda _start, _end: sessions)
    monkeypatch.setattr(
        us_hybrid_backfill,
        "_coverage",
        lambda source, symbols, start, end: {symbol: set(sessions) for symbol in symbols},
    )
    monkeypatch.setattr(
        us_hybrid_backfill,
        "run_backfill",
        lambda request, data_cfg: calls.append(request) or [],
    )

    result = us_hybrid_backfill.run_us_hybrid_backfill(
        symbol="AAPL",
        start_date=sessions[0],
        end_date=sessions[-1],
        data_cfg=SimpleNamespace(
            watchlists=SimpleNamespace(yfinance=SimpleNamespace(stocks=["AAPL"]))
        ),
    )

    assert calls == []
    assert result[-1]["alpha_requests"] == 0
    assert result[-1]["missing_after_alpha"] == 0


def test_hybrid_calls_alpha_once_for_each_recent_missing_symbol(monkeypatch) -> None:
    sessions = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    calls: list[object] = []
    primary_empty = {"AAPL": set(), "MSFT": set()}
    alpha_empty = {"AAPL": set(), "MSFT": set()}
    alpha_filled = {
        "AAPL": set(sessions),
        "MSFT": {date(2026, 10, 1), date(2026, 10, 2)},
    }

    monkeypatch.setattr(us_hybrid_backfill, "_sessions", lambda _start, _end: sessions)
    coverage_calls = iter(
        [
            primary_empty,
            alpha_empty,
            primary_empty,
            alpha_empty,
            primary_empty,
            alpha_filled,
        ]
    )
    monkeypatch.setattr(us_hybrid_backfill, "_coverage", lambda *args: next(coverage_calls))
    monkeypatch.setattr(
        us_hybrid_backfill,
        "run_backfill",
        lambda request, data_cfg: calls.append(request) or [],
    )

    result = us_hybrid_backfill.run_us_hybrid_backfill(
        symbol="AAPL,MSFT",
        start_date=sessions[0],
        end_date=sessions[-1],
        data_cfg=SimpleNamespace(
            watchlists=SimpleNamespace(yfinance=SimpleNamespace(stocks=["AAPL", "MSFT"]))
        ),
    )

    assert len(calls) == 2
    assert calls[0].data_source == "yfinance"
    assert calls[1].data_source == "alphavantage"
    assert calls[1].symbol == "AAPL,MSFT"
    assert result[-1]["alpha_requests"] == 2
    assert result[-1]["missing_after_alpha"] == 1


def test_hybrid_primary_failures_are_not_final_failures_when_alpha_fills(monkeypatch) -> None:
    sessions = [date(2026, 10, 1), date(2026, 10, 2)]
    primary_empty = {"AAPL": set()}
    alpha_empty = {"AAPL": set()}
    alpha_filled = {"AAPL": set(sessions)}
    monkeypatch.setattr(us_hybrid_backfill, "_sessions", lambda _start, _end: sessions)
    coverage_calls = iter(
        [primary_empty, alpha_empty, primary_empty, alpha_empty, primary_empty, alpha_filled]
    )
    monkeypatch.setattr(us_hybrid_backfill, "_coverage", lambda *args: next(coverage_calls))

    def fake_run_backfill(request, data_cfg):
        if request.data_source == "yfinance":
            return [{"data_source": "yfinance", "symbol": "AAPL", "failed_days": 1}]
        return [{"data_source": "alphavantage", "symbol": "AAPL", "failed_days": 0}]

    monkeypatch.setattr(us_hybrid_backfill, "run_backfill", fake_run_backfill)

    result = us_hybrid_backfill.run_us_hybrid_backfill(
        symbol="AAPL",
        start_date=sessions[0],
        end_date=sessions[-1],
        data_cfg=SimpleNamespace(
            watchlists=SimpleNamespace(yfinance=SimpleNamespace(stocks=["AAPL"]))
        ),
    )

    assert result[0]["data_source"] == "alphavantage"
    assert result[-1]["failed_days"] == 0
    assert result[-1]["primary_failed_days"] == 1
    assert result[-1]["primary_failed_symbols"] == "AAPL"
