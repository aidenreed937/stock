"""实时快照与基准的指标计算和报告表格组装。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

import polars as pl

from stock_analytics.realtime.baseline import RealtimeBaseline
from stock_analytics.realtime.cache import CacheFreshness, RealtimeSnapshotCache
from stock_data.fetcher.realtime.base import RealtimeQuote

_REPORT_COLUMNS = [
    "symbol",
    "name",
    "source",
    "quote_at",
    "received_at",
    "quote_status",
    "freshness",
    "freshness_age_seconds",
    "price",
    "pre_close",
    "baseline_close",
    "pct_change",
    "baseline_trade_date",
    "baseline_status",
    "ma20",
    "ma20_deviation_pct",
    "ma60",
    "ma60_deviation_pct",
    "realtime_amount",
    "avg_amount_20d",
    "amount_ratio_20d",
    "prior_20d_high",
    "prior_60d_low",
    "breakout_20d",
    "stop_loss_60d",
    "warning",
]


def build_report_frame(
    quotes: Sequence[RealtimeQuote],
    baselines: Mapping[str, RealtimeBaseline],
    cache: RealtimeSnapshotCache,
    now: datetime,
    *,
    max_amount_ratio: float,
) -> pl.DataFrame:
    """计算实时偏离度、成交额比和突破/止损告警。"""
    rows = []
    for quote in quotes:
        baseline = baselines.get(quote.symbol)
        cached = cache.lookup(quote.source, quote.symbol, now=now)
        freshness = cached.freshness.value if cached is not None else "missing"
        age_seconds = cached.age_seconds if cached is not None else None
        baseline_status = _resolve_baseline_status(quote, baseline)
        usable = quote.is_valid and freshness in {
            CacheFreshness.FRESH.value,
            CacheFreshness.STALE.value,
        }
        price = quote.price if usable else None
        baseline_close = baseline.yesterday_close if baseline else None
        pct_change = _deviation_percent(price, baseline_close or quote.pre_close)
        ma20_deviation = _deviation_percent(price, baseline.ma20 if baseline else None)
        ma60_deviation = _deviation_percent(price, baseline.ma60 if baseline else None)
        raw_amount_ratio = _ratio(
            value=quote.amount if usable else None,
            denominator=baseline.avg_amount_20d if baseline else None,
        )
        amount_ratio = (
            raw_amount_ratio
            if raw_amount_ratio is not None and raw_amount_ratio <= max_amount_ratio
            else None
        )
        breakout = _comparison(price, baseline.prior_20d_high if baseline else None, operator="gt")
        stop_loss = _comparison(price, baseline.prior_60d_low if baseline else None, operator="lt")
        warnings = _build_warnings(
            quote,
            freshness,
            baseline_status,
            raw_amount_ratio,
            max_amount_ratio,
            breakout,
            stop_loss,
        )
        rows.append(
            {
                "symbol": quote.symbol,
                "name": quote.name,
                "source": quote.source,
                "quote_at": _isoformat(quote.quote_at),
                "received_at": _isoformat(quote.received_at),
                "quote_status": quote.status,
                "freshness": freshness,
                "freshness_age_seconds": age_seconds,
                "price": price,
                "pre_close": quote.pre_close,
                "baseline_close": baseline_close,
                "pct_change": pct_change,
                "baseline_trade_date": baseline.baseline_trade_date if baseline else None,
                "baseline_status": baseline_status,
                "ma20": baseline.ma20 if baseline else None,
                "ma20_deviation_pct": ma20_deviation,
                "ma60": baseline.ma60 if baseline else None,
                "ma60_deviation_pct": ma60_deviation,
                "realtime_amount": quote.amount if usable else None,
                "avg_amount_20d": baseline.avg_amount_20d if baseline else None,
                "amount_ratio_20d": amount_ratio,
                "prior_20d_high": baseline.prior_20d_high if baseline else None,
                "prior_60d_low": baseline.prior_60d_low if baseline else None,
                "breakout_20d": breakout,
                "stop_loss_60d": stop_loss,
                "warning": ";".join(warnings),
            }
        )
    if not rows:
        return pl.DataFrame(schema=dict.fromkeys(_REPORT_COLUMNS, pl.String))
    return pl.DataFrame(rows).select(_REPORT_COLUMNS)


def _build_warnings(
    quote: RealtimeQuote,
    freshness: str,
    baseline_status: str,
    raw_amount_ratio: float | None,
    max_amount_ratio: float,
    breakout: bool | None,
    stop_loss: bool | None,
) -> list[str]:
    warnings: list[str] = []
    if quote.status == "missing":
        warnings.append("QUOTE_MISSING")
    elif quote.status == "invalid":
        warnings.append("QUOTE_INVALID")
    if freshness == CacheFreshness.STALE.value:
        warnings.append("QUOTE_STALE")
    if freshness == CacheFreshness.EXPIRED.value:
        warnings.append("QUOTE_EXPIRED")
    if baseline_status in {"missing", "insufficient_history"}:
        warnings.append("BASELINE_UNAVAILABLE")
    if baseline_status == "mismatch":
        warnings.append("BASELINE_MISMATCH")
    if raw_amount_ratio is not None and raw_amount_ratio > max_amount_ratio:
        warnings.append("AMOUNT_UNIT_SUSPECT")
    if breakout:
        warnings.append("BREAKOUT_20D")
    if stop_loss:
        warnings.append("STOP_LOSS_60D")
    return warnings


def _resolve_baseline_status(
    quote: RealtimeQuote,
    baseline: RealtimeBaseline | None,
) -> str:
    if baseline is None or baseline.status == "missing":
        return "missing"
    if (
        quote.pre_close is not None
        and baseline.yesterday_close is not None
        and not math.isclose(
            quote.pre_close,
            baseline.yesterday_close,
            rel_tol=0.001,
            abs_tol=0.01,
        )
    ):
        return "mismatch"
    return baseline.status


def _comparison(value: float | None, threshold: float | None, *, operator: str) -> bool | None:
    if value is None or threshold is None:
        return None
    return value > threshold if operator == "gt" else value < threshold


def _deviation_percent(value: float | None, denominator: float | None) -> float | None:
    ratio = _ratio(value=value, denominator=denominator)
    return (ratio - 1) * 100 if ratio is not None else None


def _ratio(value: float | None, denominator: float | None) -> float | None:
    if value is None or denominator is None or denominator == 0:
        return None
    return value / denominator


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = ["build_report_frame"]
