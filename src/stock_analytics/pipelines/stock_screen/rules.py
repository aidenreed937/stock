"""个股排雷规则纯函数。"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.margin_rules import evaluate_margin_stress
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    RuleEvaluator,
)
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


def evaluate_st_marked(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别 ST、*ST 与退市整理标的。"""
    pattern = str(params.get("name_regex", r"ST|\*ST|退"))
    if "name" not in rows.columns:
        return _not_evaluated(rows, "st_marked", "缺少 stock_basic.name")
    outcomes = []
    for row in _rows(rows):
        name = str(row.get("name") or "")
        matched = bool(re.search(pattern, name, flags=re.IGNORECASE))
        outcomes.append(_outcome(row, "st_marked", "fail" if matched else "pass", f"名称 {name}"))
    return _result(outcomes)


def evaluate_too_new_listing(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别上市未满观察期的次新股。"""
    if "list_date" not in rows.columns:
        return _not_evaluated(rows, "too_new_listing", "缺少 stock_basic.list_date")
    as_of = _as_of(params, rows, "list_date")
    min_days = int(params.get("min_list_days", 180))
    outcomes = []
    for row in _rows(rows):
        listed = _as_date(row.get("list_date"))
        if listed is None:
            continue
        age_days = (as_of - listed).days
        status = "fail" if age_days < min_days else "pass"
        outcomes.append(
            _outcome(
                row, "too_new_listing", status, f"上市 {listed.isoformat()}，距基准日 {age_days} 天"
            )
        )
    return _result(outcomes)


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


def evaluate_consecutive_losses(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别最近若干期净利润连续为负的股票。"""
    income_column = _first_column(rows, ("n_income", "net_income"))
    if income_column is None or "end_date" not in rows.columns:
        return _not_evaluated(rows, "consecutive_losses", "缺少 income.n_income/end_date")
    loss_years = int(params.get("loss_years", 2))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(rows):
        symbol = _symbol(row)
        end_date = _as_date(row.get("end_date"))
        value = _as_float(row.get(income_column))
        if symbol and end_date is not None and value is not None:
            grouped[symbol].append({**row, "_end_date": end_date, "_income": value})
    outcomes = []
    for symbol, values in grouped.items():
        latest_by_period: dict[int, dict[str, Any]] = {}
        for row_value in sorted(values, key=lambda item: _as_date(item["_end_date"]) or date.min):
            latest_by_period[row_value["_end_date"].year] = row_value
        periods = sorted(
            latest_by_period.values(), key=lambda item: item["_end_date"], reverse=True
        )
        selected = periods[:loss_years]
        if len(selected) < loss_years:
            status = "warn"
            reason = f"仅有 {len(selected)}/{loss_years} 期可用净利润，降级观察"
        else:
            status = "fail" if all(item["_income"] < 0 for item in selected) else "pass"
            reason = "；".join(
                f"{item['_end_date'].isoformat()} 净利润 {item['_income']:.2f}" for item in selected
            )
        outcomes.append(_outcome({"symbol": symbol}, "consecutive_losses", status, reason))
    return _result(outcomes)


def evaluate_negative_equity(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别净资产小于等于阈值的股票。"""
    column = "total_hldr_eqy_exc_min_int"
    if column not in rows.columns:
        return _not_evaluated(
            rows, "negative_equity", "缺少 balancesheet.total_hldr_eqy_exc_min_int"
        )
    threshold = float(params.get("min_total_equity", 0.0))
    outcomes = []
    for row in _latest_rows(rows):
        value = _as_float(row.get(column))
        if value is None:
            continue
        status = "fail" if value < threshold else "pass"
        outcomes.append(_outcome(row, "negative_equity", status, f"净资产 {value:.2f}"))
    return _result(outcomes)


def evaluate_goodwill_overhang(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别商誉占净资产超过硬性阈值的股票。"""
    if not {"goodwill", "total_hldr_eqy_exc_min_int"}.issubset(rows.columns):
        return _not_evaluated(rows, "goodwill_overhang", "缺少商誉或净资产字段")
    threshold = float(params.get("max_goodwill_to_equity", 0.50))
    outcomes = []
    for row in _latest_rows(rows):
        goodwill = _as_float(row.get("goodwill"))
        equity = _as_float(row.get("total_hldr_eqy_exc_min_int"))
        if goodwill is None or equity is None or equity <= 0:
            continue
        ratio = goodwill / equity
        status = "fail" if ratio > threshold else "pass"
        outcomes.append(_outcome(row, "goodwill_overhang", status, f"商誉/净资产 {ratio:.2%}"))
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
    for symbol in symbols:
        if symbol in suspended or symbol not in traded:
            status = "fail"
            reason = "基准日停牌或 stock_daily_bar 当日缺行"
        else:
            status = "pass"
            reason = "基准日有交易记录"
        outcomes.append(_outcome({"symbol": symbol}, "suspended", status, reason))
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


def evaluate_goodwill_observe(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别商誉占净资产超过观察阈值但未必硬剔除的股票。"""
    copied = dict(params)
    copied["max_goodwill_to_equity"] = float(params.get("observe_ratio", 0.30))
    result = evaluate_goodwill_overhang(rows, copied)
    if result.is_empty() or "status" not in result.columns:
        return result
    return result.with_columns(
        pl.when(pl.col("status") == "fail")
        .then(pl.lit("warn"))
        .otherwise(pl.col("status"))
        .alias("status")
    ).with_columns(pl.lit("商誉/净资产进入观察区").alias("reason"))


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
        symbol = _symbol(row)
        trade_date = _as_date(row.get("trade_date"))
        value = _as_float(row.get(value_column))
        if symbol and trade_date is not None and value is not None:
            grouped[symbol].append({"date": trade_date, "value": value})
    outcomes = []
    for symbol, values in grouped.items():
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
            _outcome(
                {"symbol": symbol}, "northbound_drawdown", status, f"北向持仓变动 {change:.2%}"
            )
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
            symbol = _symbol(row)
            trade_date = _as_date(row.get("trade_date"))
            if symbol and trade_date is not None:
                grouped[symbol].append(trade_date)
    outcomes = []
    for symbol, dates in grouped.items():
        run = _max_consecutive_run(sorted(set(dates)))
        status = "warn" if run >= minimum else "pass"
        outcomes.append(
            _outcome(
                {"symbol": symbol}, "consecutive_limit_down", status, f"连续跌停 {run} 个交易事件"
            )
        )
    return _result(outcomes)


def evaluate_rule(rule_id: str, rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """按规则 ID 调用对应的纯函数。"""
    evaluator = RULE_EVALUATORS.get(rule_id)
    if evaluator is None:
        return _not_evaluated(rows, rule_id, f"未注册规则 {rule_id}")
    return evaluator(rows, params)


RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "st_marked": evaluate_st_marked,
    "too_new_listing": evaluate_too_new_listing,
    "penny_stock_face_value": evaluate_penny_stock_face_value,
    "illiquid_float": evaluate_illiquid_float,
    "consecutive_losses": evaluate_consecutive_losses,
    "negative_equity": evaluate_negative_equity,
    "goodwill_overhang": evaluate_goodwill_overhang,
    "suspended": evaluate_suspended,
    "forecast_plunge": evaluate_forecast_plunge,
    "holder_selloff": evaluate_holder_selloff,
    "goodwill_observe": evaluate_goodwill_observe,
    "northbound_drawdown": evaluate_northbound_drawdown,
    "consecutive_limit_down": evaluate_consecutive_limit_down,
    "margin_stress": evaluate_margin_stress,
}


__all__ = [
    "RULE_EVALUATORS",
    "evaluate_consecutive_limit_down",
    "evaluate_consecutive_losses",
    "evaluate_forecast_plunge",
    "evaluate_goodwill_observe",
    "evaluate_goodwill_overhang",
    "evaluate_holder_selloff",
    "evaluate_illiquid_float",
    "evaluate_margin_stress",
    "evaluate_negative_equity",
    "evaluate_northbound_drawdown",
    "evaluate_penny_stock_face_value",
    "evaluate_rule",
    "evaluate_st_marked",
    "evaluate_suspended",
    "evaluate_too_new_listing",
]
