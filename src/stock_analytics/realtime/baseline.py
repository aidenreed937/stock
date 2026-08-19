"""从 Curated 日线黄金表提取实时监控基准。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

import polars as pl

from stock_core.contracts import MarketDataCatalog

_BASELINE_COLUMNS = ["symbol", "trade_date", "high", "low", "close", "amount"]


@dataclass(frozen=True, slots=True)
class RealtimeBaseline:
    """单个标的最近完整交易日基准。"""

    symbol: str
    dataset: str
    baseline_trade_date: date | None = None
    yesterday_close: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    avg_amount_20d: float | None = None
    prior_20d_high: float | None = None
    prior_60d_low: float | None = None
    sample_count: int = 0
    status: str = "missing"


def build_realtime_baselines(
    catalog: MarketDataCatalog,
    symbols_by_dataset: Mapping[str, Sequence[str]],
    *,
    as_of_date: date | None = None,
    lookback_days: int = 180,
) -> dict[str, RealtimeBaseline]:
    """从 Curated 日线黄金表提取实时监控所需的最近完成日基准。"""
    effective_as_of = as_of_date or date.today()
    start_date = effective_as_of - timedelta(days=max(lookback_days, 60))
    end_date = effective_as_of - timedelta(days=1)
    result: dict[str, RealtimeBaseline] = {}

    for dataset, symbols in symbols_by_dataset.items():
        requested = list(
            dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip())
        )
        if not requested:
            continue
        try:
            frame = catalog.load_bars(
                symbols=requested,
                start_date=start_date,
                end_date=end_date,
                columns=_BASELINE_COLUMNS,
                dataset=dataset,
                validate=False,
            )
        except Exception:
            frame = pl.DataFrame()
        rows_by_symbol = _group_history(frame, requested)
        for symbol in requested:
            result[symbol] = _build_baseline(symbol, dataset, rows_by_symbol.get(symbol, []))
    return result


def _group_history(
    frame: pl.DataFrame, requested: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    if frame.is_empty() or "trade_date" not in frame.columns:
        return {}
    aliases: dict[str, str] = {symbol: symbol for symbol in requested}
    code_aliases: dict[str, str] = {}
    for requested_symbol in requested:
        code = requested_symbol.split(".", 1)[0]
        if code not in code_aliases:
            code_aliases[code] = requested_symbol
        else:
            code_aliases[code] = ""

    grouped: dict[str, dict[date, dict[str, Any]]] = {}
    for raw_row in frame.iter_rows(named=True):
        raw_symbol = str(raw_row.get("symbol") or raw_row.get("ts_code") or "").strip()
        symbol: str | None = aliases.get(raw_symbol)
        if symbol is None and "." not in raw_symbol:
            candidate = code_aliases.get(raw_symbol, "")
            symbol = candidate or None
        parsed_date = _coerce_date(raw_row.get("trade_date"))
        if symbol is None or parsed_date is None:
            continue
        row = {
            "trade_date": parsed_date,
            "high": _coerce_float(raw_row.get("high")),
            "low": _coerce_float(raw_row.get("low")),
            "close": _coerce_float(raw_row.get("close")),
            "amount": _coerce_float(raw_row.get("amount")),
        }
        grouped.setdefault(symbol, {})[parsed_date] = row
    return {
        symbol: sorted(rows.values(), key=lambda row: row["trade_date"])
        for symbol, rows in grouped.items()
    }


def _build_baseline(
    symbol: str,
    dataset: str,
    history: list[dict[str, Any]],
) -> RealtimeBaseline:
    if not history:
        return RealtimeBaseline(symbol=symbol, dataset=dataset)
    latest = history[-1]
    closes = [row["close"] for row in history if _positive(row.get("close"))]
    previous_20 = history[-20:]
    previous_60 = history[-60:]
    ma20 = fmean(closes[-20:]) if len(closes) >= 20 else None
    ma60 = fmean(closes[-60:]) if len(closes) >= 60 else None
    amounts = [row["amount"] for row in history[-20:] if _positive(row.get("amount"))]
    avg_amount = fmean(amounts) if len(amounts) == 20 else None
    highs = [row["high"] for row in previous_20 if _positive(row.get("high"))]
    lows = [row["low"] for row in previous_60 if _positive(row.get("low"))]
    return RealtimeBaseline(
        symbol=symbol,
        dataset=dataset,
        baseline_trade_date=latest["trade_date"],
        yesterday_close=latest.get("close"),
        ma20=ma20,
        ma60=ma60,
        avg_amount_20d=avg_amount,
        prior_20d_high=max(highs) if len(highs) == 20 else None,
        prior_60d_low=min(lows) if len(lows) == 60 else None,
        sample_count=len(history),
        status=(
            "available"
            if _positive(latest.get("close")) and ma20 is not None
            else "insufficient_history"
        ),
    )


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _coerce_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(value) and value > 0


__all__ = ["RealtimeBaseline", "build_realtime_baselines"]
