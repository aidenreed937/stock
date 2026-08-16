"""Alpha Vantage global FX data fetcher."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.alphavantage.client import AlphaVantageClient


_FX_SYMBOLS: dict[str, tuple[str, str, str]] = {
    "CNH=X": ("USD", "CNH", "CNH=X"),
    "USD/CNH": ("USD", "CNH", "CNH=X"),
    "USD_CNH": ("USD", "CNH", "CNH=X"),
    "CNH": ("USD", "CNH", "CNH=X"),
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_fx_symbol(symbol: str) -> tuple[str, str, str]:
    key = symbol.strip().upper() or "CNH=X"
    try:
        return _FX_SYMBOLS[key]
    except KeyError as exc:
        raise ValueError(
            f"暂不支持 Alpha Vantage 外汇标的 [{symbol}]；当前支持 CNH=X/USD/CNH"
        ) from exc


class AlphaVantageDataFetcher(BaseDataFetcher):
    """Alpha Vantage daily FX fetcher."""

    def __init__(
        self,
        client: AlphaVantageClient | None = None,
        proxy: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.client = client or AlphaVantageClient(api_key=api_key, proxy=proxy)

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        """Return the weekday calendar used by the FX daily endpoint."""
        return [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
            if (start_date + timedelta(days=offset)).weekday() < 5
        ]

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[Any]:
        return []

    def fetch_fx_daily_df(
        self, symbol: str, start_date: date, end_date: date
    ) -> pl.DataFrame:
        from_symbol, to_symbol, canonical_symbol = _parse_fx_symbol(symbol)
        raw_series = self.client.fetch_fx_daily_raw(from_symbol, to_symbol)
        rows: list[dict[str, Any]] = []
        for date_text, values in raw_series.items():
            try:
                trade_date = datetime.strptime(str(date_text), "%Y-%m-%d").date()
            except ValueError:
                continue
            if not start_date <= trade_date <= end_date or not isinstance(values, dict):
                continue

            open_value = _number(values.get("1. open"))
            high_value = _number(values.get("2. high"))
            low_value = _number(values.get("3. low"))
            close_value = _number(values.get("4. close"))
            if None in (open_value, high_value, low_value, close_value):
                continue
            rows.append(
                {
                    "symbol": canonical_symbol,
                    "trade_date": trade_date,
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                    "volume": 0.0,
                    "amount": 0.0,
                }
            )

        return pl.DataFrame(
            rows,
            schema={
                "symbol": pl.String,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "amount": pl.Float64,
            },
        ).sort("trade_date")

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "fx_daily",
        **kwargs: Any,
    ) -> pl.DataFrame:
        if endpoint.upper() != "FX_DAILY" and endpoint != "fx_daily":
            raise ValueError(f"Unsupported Alpha Vantage endpoint: {endpoint}")
        return self.fetch_fx_daily_df(symbol, start_date, end_date)
