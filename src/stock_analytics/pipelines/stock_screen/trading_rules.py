"""个股排雷交易与市场事件规则纯函数。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.rule_helpers import (
    as_date as _as_date,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    as_float as _as_float,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    as_of as _as_of,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    count_results as _count_results,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    first_column as _first_column,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    is_limit_down as _is_limit_down,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    latest_rows as _latest_rows,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    max_consecutive_run as _max_consecutive_run,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    not_evaluated as _not_evaluated,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    outcome as _outcome,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    result_frame as _result,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    rows as _rows,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    symbol as _symbol,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    unique_symbols as _unique_symbols,
)


def evaluate_penny_stock_face_value(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别收盘价低于面值风险阈值的股票。"""
    column = _first_column(rows, ("close", "price"))
    if column is None:
        return _not_evaluated(rows, "penny_stock_face_value", "缺少 daily_basic.close")
    threshold = float(params.get("min_close_price", 2.0))
    outcomes = []
    for row in _latest_rows(rows, date_column="trade_date"):
        value = _as_float(row.get(column))
        if value is None:
            continue
        status = "fail" if value < threshold else "pass"
        outcomes.append(_outcome(row, "penny_stock_face_value", status, f"收盘价 {value:.2f} 元"))
    return _result(outcomes)


def evaluate_illiquid_float(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别日成交额低于流动性阈值的股票。"""
    if "amount" not in rows.columns:
        return _not_evaluated(rows, "illiquid_float", "缺少 stock_daily_bar.amount")
    threshold = float(params.get("min_daily_amount_yuan", 50_000_000.0))
    outcomes = []
    for row in _latest_rows(rows, date_column="trade_date"):
        value = _as_float(row.get("amount"))
        if value is None:
            continue
        status = "fail" if value < threshold else "pass"
        outcomes.append(_outcome(row, "illiquid_float", status, f"日成交额 {value:.0f} 元"))
    return _result(outcomes)


def evaluate_suspended(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别基准日无交易或被记录为停牌的股票。"""
    symbols = [str(value) for value in params.get("universe_symbols", ())]
    if not symbols:
        symbols = _unique_symbols(rows)
    as_of = _as_of(params, rows, "trade_date")
    traded = {
        _symbol(row)
        for row in _rows(rows)
        if _symbol(row) and _as_date(row.get("trade_date")) == as_of
    }
    suspended = {
        _symbol(row)
        for row in _rows(rows)
        if _symbol(row)
        and (
            _as_date(row.get("suspend_date")) == as_of
            or (row.get("suspend_type") is not None and _as_date(row.get("trade_date")) == as_of)
        )
    }
    outcomes = []
    for sym in symbols:
        if sym in suspended or sym not in traded:
            status = "fail"
            reason = "基准日停牌或 stock_daily_bar 当日缺行"
        else:
            status = "pass"
            reason = "基准日有交易记录"
        outcomes.append(_outcome({"symbol": sym}, "suspended", status, reason))
    return _result(outcomes)


def evaluate_forecast_plunge(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别业绩预告下修幅度超过阈值的股票。"""
    column = "p_change_min"
    if column not in rows.columns:
        return _not_evaluated(rows, "forecast_plunge", "缺少 forecast.p_change_min")
    threshold = float(params.get("p_change_min_threshold", -50.0))
    outcomes = []
    for row in _latest_rows(rows, date_column="ann_date"):
        value = _as_float(row.get(column))
        if value is None:
            continue
        status = "warn" if value < threshold else "pass"
        outcomes.append(_outcome(row, "forecast_plunge", status, f"业绩预告变动下限 {value:.2f}%"))
    return _result(outcomes)


def evaluate_holder_selloff(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别窗口内大股东或董监高持续减持事件。"""
    if not {"in_de"}.issubset(rows.columns):
        return _not_evaluated(rows, "holder_selloff", "缺少 stk_holdertrade.in_de")
    as_of = _as_of(params, rows, "ann_date")
    window_days = int(params.get("window_days", 180))
    min_count = int(params.get("min_sell_count", 3))
    start = as_of - timedelta(days=window_days)
    counts: dict[str, int] = defaultdict(int)
    for row in _rows(rows):
        event_date = _as_date(row.get("close_date")) or _as_date(row.get("begin_date"))
        event_date = event_date or _as_date(row.get("ann_date"))
        if event_date is None or not start <= event_date <= as_of:
            continue
        if str(row.get("in_de") or "").strip().upper() == "DE":
            counts[_symbol(row)] += 1
    return _count_results(counts, "holder_selloff", min_count, "半年减持笔数")


def evaluate_northbound_drawdown(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别北向持仓相对窗口起点的骤降。"""
    if "trade_date" not in rows.columns:
        return _not_evaluated(rows, "northbound_drawdown", "缺少 hk_hold.trade_date")
    value_column = _first_column(rows, ("vol", "sharehold", "hold_vol", "shareholding", "ratio"))
    if value_column is None:
        return _not_evaluated(rows, "northbound_drawdown", "缺少 hk_hold 持仓数量字段")
    window = int(params.get("window_days", 20))
    threshold = float(params.get("drop_threshold", -0.20))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(rows):
        sym = _symbol(row)
        trade_date = _as_date(row.get("trade_date"))
        value = _as_float(row.get(value_column))
        if sym and trade_date is not None and value is not None:
            grouped[sym].append({"date": trade_date, "value": value})
    outcomes = []
    for sym, values in grouped.items():
        values.sort(key=lambda item: item["date"])
        if len(values) <= window:
            continue
        previous = values[-window - 1]["value"]
        current = values[-1]["value"]
        if previous <= 0:
            continue
        change = current / previous - 1.0
        status = "warn" if change < threshold else "pass"
        outcomes.append(
            _outcome({"symbol": sym}, "northbound_drawdown", status, f"北向持仓变动 {change:.2%}")
        )
    return _result(outcomes)


def evaluate_consecutive_limit_down(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别连续跌停事件。"""
    if "trade_date" not in rows.columns:
        return _not_evaluated(rows, "consecutive_limit_down", "缺少 limit_list_d.trade_date")
    minimum = int(params.get("min_consecutive_count", 2))
    grouped: dict[str, list[date]] = defaultdict(list)
    for row in _rows(rows):
        if _is_limit_down(row):
            sym = _symbol(row)
            trade_date = _as_date(row.get("trade_date"))
            if sym and trade_date is not None:
                grouped[sym].append(trade_date)
    outcomes = []
    for sym, dates in grouped.items():
        run = _max_consecutive_run(sorted(set(dates)))
        status = "warn" if run >= minimum else "pass"
        outcomes.append(
            _outcome(
                {"symbol": sym}, "consecutive_limit_down", status, f"连续跌停 {run} 个交易事件"
            )
        )
    return _result(outcomes)


def evaluate_lockup_release(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别未来窗口期内面临大额限售股解禁洪峰的标的。"""
    if "float_date" not in rows.columns:
        return _not_evaluated(rows, "lockup_release", "缺少 share_float.float_date")
    ratio_col = _first_column(rows, ("float_ratio", "ratio"))
    as_of = _as_of(params, rows, "ann_date")
    forward_days = int(params.get("forward_days", 60))
    threshold = float(params.get("max_float_ratio", 10.0))
    end_window = as_of + timedelta(days=forward_days)

    grouped_ratio: dict[str, float] = defaultdict(float)
    for row in _rows(rows):
        ann = _as_date(row.get("ann_date"))
        float_d = _as_date(row.get("float_date"))
        if ann is not None and ann > as_of:
            continue
        if float_d is None or not (as_of < float_d <= end_window):
            continue
        val = _as_float(row.get(ratio_col)) if ratio_col else None
        if val is not None:
            grouped_ratio[_symbol(row)] += val

    symbols = [str(v) for v in params.get("universe_symbols", ())] or _unique_symbols(rows)
    outcomes = []
    for sym in symbols:
        total_ratio = grouped_ratio.get(sym, 0.0)
        status = "warn" if total_ratio >= threshold else "pass"
        reason = (
            f"未来 {forward_days} 天限售解禁 {total_ratio:.2f}%"
            if total_ratio > 0
            else f"未来 {forward_days} 天无大额解禁"
        )
        outcomes.append(_outcome({"symbol": sym}, "lockup_release", status, reason))
    return _result(outcomes)


def evaluate_block_trade_discount(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别近期大宗交易大额减持套现的标的。"""
    if "amount" not in rows.columns or "trade_date" not in rows.columns:
        return _not_evaluated(rows, "block_trade_discount", "缺少 block_trade.amount/trade_date")
    as_of = _as_of(params, rows, "trade_date")
    window_days = int(params.get("window_days", 30))
    min_amount = float(params.get("min_total_amount", 20_000_000.0))
    start_date = as_of - timedelta(days=window_days)

    amounts: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in _rows(rows):
        t_date = _as_date(row.get("trade_date"))
        amt = _as_float(row.get("amount"))
        if t_date is not None and start_date <= t_date <= as_of and amt is not None:
            amounts[_symbol(row)] += amt
            counts[_symbol(row)] += 1

    symbols = [str(v) for v in params.get("universe_symbols", ())] or _unique_symbols(rows)
    outcomes = []
    for sym in symbols:
        tot_amt = amounts.get(sym, 0.0)
        cnt = counts.get(sym, 0)
        status = "warn" if tot_amt >= min_amount else "pass"
        reason = (
            f"近 {window_days} 天大宗交易 {cnt} 笔，累计 {tot_amt / 10000:.0f} 万元"
            if cnt > 0
            else f"近 {window_days} 天无大额大宗交易"
        )
        outcomes.append(_outcome({"symbol": sym}, "block_trade_discount", status, reason))
    return _result(outcomes)


__all__ = [
    "evaluate_block_trade_discount",
    "evaluate_consecutive_limit_down",
    "evaluate_forecast_plunge",
    "evaluate_holder_selloff",
    "evaluate_illiquid_float",
    "evaluate_lockup_release",
    "evaluate_northbound_drawdown",
    "evaluate_penny_stock_face_value",
    "evaluate_suspended",
]
