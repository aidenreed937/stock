"""全市场聚合短期历史对比。"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.pipelines.market_aggregate.trend_summary import build_trend_summary
from stock_core.contracts import MarketDataCatalog
from stock_data.fetcher.realtime.market_aggregate import (
    MarketAggregateSnapshot,
    _aggregate_rows,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_HISTORY_BAR_COLUMNS = (
    "trade_date",
    "symbol",
    "close",
    "pre_close",
    "pct_chg",
    "amount",
)
_DAILY_BASIC_COLUMNS = ("trade_date", "symbol", "circ_mv", "total_mv")
_TREND_FACT_COLUMNS = (
    "date",
    "source",
    "status",
    "reported_count",
    "returned_count",
    "coverage_ratio",
    "advance_count",
    "decline_count",
    "flat_count",
    "advance_share",
    "decline_share",
    "advance_decline_ratio",
    "strong_up_count",
    "strong_down_count",
    "strong_up_share",
    "strong_down_share",
    "median_pct_change",
    "pct_change_p25",
    "pct_change_p75",
    "weighted_pct_change",
    "amount_total_yuan",
    "total_market_value_yuan",
    "free_float_market_value_yuan",
    "free_float_turnover_pct",
    "amount_top_5pct_share",
)


def build_short_term_trend(
    catalog: MarketDataCatalog | None,
    current_snapshot: MarketAggregateSnapshot,
    *,
    prior_trade_days: int = 4,
    lookback_calendar_days: int = 30,
    strong_move_threshold_pct: float = 5.0,
    bars_dataset: str = "stock_daily_bar",
    market_value_dataset: str = "daily_basic",
) -> dict[str, Any]:
    """构造“今日实时快照 + 前 N 个交易日历史聚合”的短期趋势。"""
    as_of_date = current_snapshot.quote_date
    prior_trade_days = max(1, prior_trade_days)
    result = {
        "status": "unavailable",
        "as_of_date": as_of_date.isoformat(),
        "prior_trade_days": prior_trade_days,
        "history_dates": [],
        "rows": [],
        "summary": {},
        "reason": "",
    }
    if catalog is None:
        result["reason"] = "未提供本地历史数据目录。"
        return result

    end_date = as_of_date - timedelta(days=1)
    start_date = as_of_date - timedelta(days=max(lookback_calendar_days, prior_trade_days * 3))
    try:
        bars = catalog.load_dataset(
            bars_dataset,
            start_date=start_date,
            end_date=end_date,
            columns=_HISTORY_BAR_COLUMNS,
        )
    except (OSError, TypeError, ValueError) as exc:
        result["reason"] = f"本地 stock_daily_bar 读取失败：{exc}"
        return result

    bars = _filter_a_share_scope(bars)
    if bars.is_empty() or "trade_date" not in bars.columns:
        result["reason"] = "本地 stock_daily_bar 没有可用于前4个交易日对比的数据。"
        return result

    available_dates = (
        bars.select("trade_date")
        .drop_nulls()
        .unique()
        .sort("trade_date")
        .get_column("trade_date")
        .to_list()
    )
    history_dates = [value for value in available_dates if value < as_of_date][-prior_trade_days:]
    if not history_dates:
        result["reason"] = "本地 stock_daily_bar 没有早于当前快照日期的交易日。"
        return result

    cap_lookup = _load_market_values(catalog, market_value_dataset, start_date, end_date)
    history_rows = [
        _build_history_row(
            bars.filter(pl.col("trade_date") == trade_date),
            trade_date=trade_date,
            reported_count=current_snapshot.reported_count,
            cap_lookup=cap_lookup,
            strong_move_threshold_pct=strong_move_threshold_pct,
        )
        for trade_date in history_dates
    ]
    current_row = _trend_row(current_snapshot, source="tencent_realtime")
    rows = [*history_rows, current_row]
    status = "available" if len(history_rows) == prior_trade_days else "partial"
    result.update(
        {
            "status": status,
            "history_dates": [value.isoformat() for value in history_dates],
            "rows": rows,
            "summary": build_trend_summary(history_rows, current_row),
            "reason": (
                ""
                if status == "available"
                else f"本地仅找到 {len(history_rows)}/{prior_trade_days} 个前置交易日。"
            ),
        }
    )
    return result


def build_trend_facts(trend: dict[str, Any]) -> pl.DataFrame:
    """将趋势结果整理为稳定 Schema 的 Parquet 事实表。"""
    rows = trend.get("rows") or []
    if not rows:
        return pl.DataFrame(schema=dict.fromkeys(_TREND_FACT_COLUMNS, pl.String))
    return pl.DataFrame(rows).select(
        [column for column in _TREND_FACT_COLUMNS if column in rows[0]]
    )


def _build_history_row(
    frame: pl.DataFrame,
    *,
    trade_date: date,
    reported_count: int,
    cap_lookup: dict[tuple[date, str], tuple[float | None, float | None]],
    strong_move_threshold_pct: float,
) -> dict[str, Any]:
    rows: list[dict[str, float | None]] = []
    for raw in frame.iter_rows(named=True):
        symbol = str(raw.get("symbol") or "")
        close = _as_float(raw.get("close"))
        pre_close = _as_float(raw.get("pre_close"))
        pct_change = _as_float(raw.get("pct_chg"))
        if pct_change is None and close is not None and pre_close and pre_close > 0:
            pct_change = (close - pre_close) / pre_close * 100
        free_float_mv, total_mv = cap_lookup.get((trade_date, symbol), (None, None))
        rows.append(
            {
                "price": close,
                "change": pct_change,
                "amount": _as_float(raw.get("amount")),
                "total_market_value_yuan": total_mv,
                "free_float_market_value_yuan": free_float_mv,
            }
        )

    timestamp = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        15,
        0,
        tzinfo=_SHANGHAI_TZ,
    )
    snapshot = _aggregate_rows(
        rows,
        reported_count=reported_count,
        received_at=timestamp,
        quote_at=timestamp,
        source="curated_stock_daily_bar",
        strong_move_threshold_pct=strong_move_threshold_pct,
    )
    return _trend_row(snapshot, source="curated_stock_daily_bar")


def _load_market_values(
    catalog: MarketDataCatalog,
    dataset: str,
    start_date: date,
    end_date: date,
) -> dict[tuple[date, str], tuple[float | None, float | None]]:
    try:
        basic = catalog.load_dataset(
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=_DAILY_BASIC_COLUMNS,
        )
    except (OSError, TypeError, ValueError):
        return {}
    basic = _filter_a_share_scope(basic)
    if basic.is_empty() or not {"trade_date", "symbol"}.issubset(basic.columns):
        return {}
    return {
        (row["trade_date"], str(row["symbol"])): (
            _as_float(row.get("circ_mv")),
            _as_float(row.get("total_mv")),
        )
        for row in basic.iter_rows(named=True)
        if row.get("trade_date") is not None and row.get("symbol") is not None
    }


def _filter_a_share_scope(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "symbol" not in frame.columns:
        return pl.DataFrame()
    if "trade_date" not in frame.columns:
        return pl.DataFrame()
    trade_date_dtype = frame.schema["trade_date"]
    if trade_date_dtype == pl.String:
        trade_date_expr = pl.col("trade_date").str.to_date(strict=False)
    elif isinstance(trade_date_dtype, pl.Datetime):
        trade_date_expr = pl.col("trade_date").dt.date()
    else:
        trade_date_expr = pl.col("trade_date").cast(pl.Date, strict=False)
    result = frame.with_columns(
        pl.col("symbol").cast(pl.Utf8).alias("symbol"),
        trade_date_expr.alias("trade_date"),
    )
    return result.filter(
        pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")
    )


def _trend_row(snapshot: MarketAggregateSnapshot, *, source: str) -> dict[str, Any]:
    return {
        "date": snapshot.quote_date.isoformat(),
        "source": source,
        "status": snapshot.status,
        "reported_count": snapshot.reported_count,
        "returned_count": snapshot.returned_count,
        "coverage_ratio": snapshot.coverage_ratio,
        "advance_count": snapshot.advance_count,
        "decline_count": snapshot.decline_count,
        "flat_count": snapshot.flat_count,
        "advance_share": snapshot.advance_share,
        "decline_share": snapshot.decline_share,
        "advance_decline_ratio": snapshot.advance_decline_ratio,
        "strong_up_count": snapshot.strong_up_count,
        "strong_down_count": snapshot.strong_down_count,
        "strong_up_share": snapshot.strong_up_share,
        "strong_down_share": snapshot.strong_down_share,
        "median_pct_change": snapshot.median_pct_change,
        "pct_change_p25": snapshot.pct_change_p25,
        "pct_change_p75": snapshot.pct_change_p75,
        "weighted_pct_change": snapshot.weighted_pct_change,
        "amount_total_yuan": snapshot.amount_total_yuan,
        "total_market_value_yuan": snapshot.total_market_value_yuan,
        "free_float_market_value_yuan": snapshot.free_float_market_value_yuan,
        "free_float_turnover_pct": snapshot.free_float_turnover_pct,
        "amount_top_5pct_share": snapshot.amount_top_5pct_share,
    }


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = ["build_short_term_trend", "build_trend_facts"]
