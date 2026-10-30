"""Alpha Vantage 行情、外汇与公司基本面数据抓取器。"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.models.market import DailyBar
from stock_data.fetcher.alphavantage.client import AlphaVantageClient
from stock_data.fetcher.base import BaseDataFetcher

_FX_SYMBOLS: dict[str, tuple[str, str, str]] = {
    "CNH=X": ("USD", "CNH", "CNH=X"),
    "USD/CNH": ("USD", "CNH", "CNH=X"),
    "USD_CNH": ("USD", "CNH", "CNH=X"),
    "CNH": ("USD", "CNH", "CNH=X"),
}
_DAILY_SERIES_KEY = "Time Series (Daily)"


def _snake_case_column_name(name: object) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()


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


def _coerce_alpha_value(key: str, value: Any) -> Any:
    """将 Alpha Vantage 基本面标量转换为可落盘的标准 Python 值。"""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "-"}:
        return None
    if key in {"symbol", "cik", "exchange", "currency", "country", "sector", "industry"}:
        return text
    number = _number(text)
    return number if number is not None else text


def _normalize_alpha_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        _snake_case_column_name(key): _coerce_alpha_value(_snake_case_column_name(key), value)
        for key, value in record.items()
    }


def _statement_rows(payload: dict[str, Any], symbol: str, report_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    report_groups = (
        ("annual", payload.get("annualReports")),
        ("quarterly", payload.get(report_key)),
    )
    for report_type, raw_rows in report_groups:
        if not isinstance(raw_rows, list):
            continue
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            normalized = _normalize_alpha_record(raw_row)
            fiscal_date = normalized.get("fiscal_date_ending")
            if not fiscal_date:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "report_type": report_type,
                    **normalized,
                }
            )
    return rows


class AlphaVantageDataFetcher(BaseDataFetcher):
    """Alpha Vantage daily equity, FX and company fundamental fetcher."""

    def __init__(
        self,
        client: AlphaVantageClient | None = None,
        proxy: str | None = None,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        daily_limit: int | None = None,
        usage_file: str | Path | None = None,
    ) -> None:
        self.client = client or AlphaVantageClient(
            api_key=api_key,
            api_keys=api_keys,
            proxy=proxy,
            daily_limit=daily_limit,
            usage_file=usage_file,
        )

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        """Return the weekday calendar used by Alpha Vantage daily endpoints."""
        return [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
            if (start_date + timedelta(days=offset)).weekday() < 5
        ]

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        raw_payload = self.client.fetch_daily_raw(symbol)
        raw_series = raw_payload.get(_DAILY_SERIES_KEY)
        if not isinstance(raw_series, dict):
            raise ValueError(f"Alpha Vantage 日线响应缺少 [{_DAILY_SERIES_KEY}]")

        bars: list[DailyBar] = []
        for date_text, values in raw_series.items():
            if not isinstance(values, dict):
                continue
            try:
                trade_date = datetime.strptime(str(date_text), "%Y-%m-%d").date()
            except ValueError:
                continue
            if not start_date <= trade_date <= end_date:
                continue

            open_value = _number(values.get("1. open"))
            high_value = _number(values.get("2. high"))
            low_value = _number(values.get("3. low"))
            close_value = _number(values.get("4. close"))
            volume_value = _number(values.get("5. volume"))
            if (
                open_value is None
                or high_value is None
                or low_value is None
                or close_value is None
                or volume_value is None
            ):
                continue
            if min(open_value, high_value, low_value, close_value) <= 0 or volume_value < 0:
                continue

            bars.append(
                DailyBar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=open_value,
                    high=high_value,
                    low=low_value,
                    close=close_value,
                    volume=volume_value,
                    amount=volume_value * close_value,
                )
            )
        return sorted(bars, key=lambda bar: bar.trade_date)

    def fetch_fx_daily_df(self, symbol: str, start_date: date, end_date: date) -> pl.DataFrame:
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

    def fetch_company_overview_df(self, symbol: str) -> pl.DataFrame:
        payload = self.client.fetch_company_overview_raw(symbol)
        if not payload or not payload.get("Symbol"):
            return pl.DataFrame()
        row = _normalize_alpha_record(payload)
        row["symbol"] = symbol
        row["as_of_date"] = row.get("latest_quarter")
        return pl.DataFrame([row])

    def fetch_earnings_df(self, symbol: str) -> pl.DataFrame:
        payload = self.client.fetch_earnings_raw(symbol)
        rows: list[dict[str, Any]] = []
        for report_type, key in (("annual", "annualEarnings"), ("quarterly", "quarterlyEarnings")):
            raw_rows = payload.get(key)
            if not isinstance(raw_rows, list):
                continue
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    continue
                normalized = _normalize_alpha_record(raw_row)
                if normalized.get("fiscal_date_ending"):
                    rows.append({"symbol": symbol, "report_type": report_type, **normalized})
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    def fetch_statement_df(self, symbol: str, statement_type: str) -> pl.DataFrame:
        payload = self.client.fetch_statement_raw(symbol, statement_type)
        rows = _statement_rows(payload, symbol, "quarterlyReports")
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "fx_daily",
        **kwargs: Any,
    ) -> pl.DataFrame:
        endpoint_upper = endpoint.upper()
        if endpoint_upper == "OVERVIEW":
            return self.fetch_company_overview_df(symbol)
        if endpoint_upper == "EARNINGS":
            return self.fetch_earnings_df(symbol)
        if endpoint_upper in {"INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"}:
            statement_type = {
                "INCOME_STATEMENT": "financials",
                "BALANCE_SHEET": "balance_sheet",
                "CASH_FLOW": "cashflow",
            }[endpoint_upper]
            return self.fetch_statement_df(symbol, statement_type)
        if endpoint_upper in {"TIME_SERIES_DAILY", "STOCK_DAILY_BAR"}:
            bars = self.fetch_daily_bars(symbol, start_date, end_date)
            return pl.DataFrame([bar.model_dump() for bar in bars]) if bars else pl.DataFrame()
        if endpoint.upper() != "FX_DAILY" and endpoint != "fx_daily":
            raise ValueError(f"Unsupported Alpha Vantage endpoint: {endpoint}")
        return self.fetch_fx_daily_df(symbol, start_date, end_date)
