"""个股排雷基本面与财务规则纯函数。"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
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
    first_column as _first_column,
)
from stock_analytics.pipelines.stock_screen.rule_helpers import (
    latest_rows as _latest_rows,
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


def evaluate_consecutive_losses(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别最近若干期净利润连续为负的股票。"""
    income_column = _first_column(rows, ("n_income", "net_income"))
    if income_column is None or "end_date" not in rows.columns:
        return _not_evaluated(rows, "consecutive_losses", "缺少 income.n_income/end_date")
    loss_years = int(params.get("loss_years", 2))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(rows):
        sym = _symbol(row)
        end_date = _as_date(row.get("end_date"))
        value = _as_float(row.get(income_column))
        if sym and end_date is not None and value is not None:
            grouped[sym].append({**row, "_end_date": end_date, "_income": value})
    outcomes = []
    for sym, values in grouped.items():
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
        outcomes.append(_outcome({"symbol": sym}, "consecutive_losses", status, reason))
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


def evaluate_dedt_profit_loss(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别扣非净利润连续为负的标的（主业空心化风险）。"""
    column = "profit_dedt"
    if column not in rows.columns or "end_date" not in rows.columns:
        return _not_evaluated(rows, "dedt_profit_loss", "缺少 fina_indicator.profit_dedt/end_date")
    loss_years = int(params.get("loss_years", 2))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(rows):
        sym = _symbol(row)
        end_date = _as_date(row.get("end_date"))
        value = _as_float(row.get(column))
        if sym and end_date is not None and value is not None:
            grouped[sym].append({**row, "_end_date": end_date, "_dedt": value})
    outcomes = []
    for sym, values in grouped.items():
        latest_by_period: dict[int, dict[str, Any]] = {}
        for row_value in sorted(values, key=lambda item: _as_date(item["_end_date"]) or date.min):
            latest_by_period[row_value["_end_date"].year] = row_value
        periods = sorted(
            latest_by_period.values(), key=lambda item: item["_end_date"], reverse=True
        )
        selected = periods[:loss_years]
        if len(selected) < loss_years:
            status = "warn"
            reason = f"仅有 {len(selected)}/{loss_years} 期可用扣非净利润，降级观察"
        else:
            status = "warn" if all(item["_dedt"] < 0 for item in selected) else "pass"
            reason = "；".join(
                f"{item['_end_date'].isoformat()} 扣非净利润 {item['_dedt']:.2f}"
                for item in selected
            )
        outcomes.append(_outcome({"symbol": sym}, "dedt_profit_loss", status, reason))
    return _result(outcomes)


def evaluate_high_leverage_insolvency(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别资产负债率畸高且流动性偿债指标恶化的标的。"""
    if "debt_to_assets" not in rows.columns:
        return _not_evaluated(
            rows, "high_leverage_insolvency", "缺少 fina_indicator.debt_to_assets"
        )
    max_debt = float(params.get("max_debt_to_assets", 85.0))
    min_cr = float(params.get("min_current_ratio", 0.8))
    outcomes = []
    for row in _latest_rows(rows, date_column="ann_date"):
        debt = _as_float(row.get("debt_to_assets"))
        cr = _as_float(row.get("current_ratio"))
        if debt is None:
            continue
        if (debt >= max_debt and (cr is not None and cr <= min_cr)) or debt >= 95.0:
            status = "warn"
            cr_text = f"，流动比率 {cr:.2f}" if cr is not None else ""
            reason = f"资产负债率 {debt:.2f}%{cr_text}"
        else:
            status = "pass"
            reason = f"资产负债率 {debt:.2f}%，偿债指标正常"
        outcomes.append(_outcome(row, "high_leverage_insolvency", status, reason))
    return _result(outcomes)


def evaluate_receivables_revenue_distortion(
    rows: pl.DataFrame, params: dict[str, Any]
) -> pl.DataFrame:
    """识别应收账款占营业收入过高的标的（财报失真与坏账风险）。"""
    if not {"accounts_receiv"}.issubset(rows.columns):
        return _not_evaluated(rows, "receivables_revenue_distortion", "缺少 accounts_receiv 字段")
    rev_col = _first_column(rows, ("revenue", "total_revenue"))
    if rev_col is None:
        return _not_evaluated(
            rows, "receivables_revenue_distortion", "缺少 revenue/total_revenue 字段"
        )
    threshold = float(params.get("max_receivables_ratio", 0.80))
    outcomes = []
    for row in _latest_rows(rows, date_column="ann_date"):
        ar = _as_float(row.get("accounts_receiv"))
        rev = _as_float(row.get(rev_col))
        if ar is None or rev is None or rev <= 0:
            continue
        ratio = ar / rev
        status = "warn" if ratio >= threshold else "pass"
        outcomes.append(
            _outcome(
                row,
                "receivables_revenue_distortion",
                status,
                f"应收账款/营业收入 {ratio:.2%}",
            )
        )
    return _result(outcomes)


def evaluate_consecutive_ocf_deficit(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别经营活动现金流量净额连续为负的标的（造血能力枯竭）。"""
    column = "n_cashflow_act"
    if column not in rows.columns or "end_date" not in rows.columns:
        return _not_evaluated(
            rows, "consecutive_ocf_deficit", "缺少 cashflow.n_cashflow_act/end_date"
        )
    loss_years = int(params.get("loss_years", 2))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(rows):
        sym = _symbol(row)
        end_date = _as_date(row.get("end_date"))
        value = _as_float(row.get(column))
        if sym and end_date is not None and value is not None:
            grouped[sym].append({**row, "_end_date": end_date, "_ocf": value})
    outcomes = []
    for sym, values in grouped.items():
        latest_by_period: dict[int, dict[str, Any]] = {}
        for row_value in sorted(values, key=lambda item: _as_date(item["_end_date"]) or date.min):
            latest_by_period[row_value["_end_date"].year] = row_value
        periods = sorted(
            latest_by_period.values(), key=lambda item: item["_end_date"], reverse=True
        )
        selected = periods[:loss_years]
        if len(selected) < loss_years:
            status = "warn"
            reason = f"仅有 {len(selected)}/{loss_years} 期可用经营现金流，降级观察"
        else:
            status = "warn" if all(item["_ocf"] < 0 for item in selected) else "pass"
            reason = "；".join(
                f"{item['_end_date'].isoformat()} 经营现金流 {item['_ocf']:.2f}"
                for item in selected
            )
        outcomes.append(_outcome({"symbol": sym}, "consecutive_ocf_deficit", status, reason))
    return _result(outcomes)


def evaluate_pledge_overhang(rows: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """识别股权质押比例过高的标的（爆仓平仓风险）。"""
    if not {"pledge_amount"}.issubset(rows.columns):
        return _not_evaluated(rows, "pledge_overhang", "缺少 pledge_detail.pledge_amount")
    as_of = _as_of(params, rows, "ann_date")
    threshold = float(params.get("max_pledge_ratio", 0.50))

    pledge_totals: dict[str, float] = defaultdict(float)
    holding_totals: dict[str, float] = defaultdict(float)
    for row in _rows(rows):
        ann = _as_date(row.get("ann_date"))
        if ann is not None and ann > as_of:
            continue
        is_rel = str(row.get("is_release") or "").strip()
        rel_date = _as_date(row.get("release_date"))
        if is_rel in {"1", "Y"} and rel_date is not None and rel_date <= as_of:
            continue
        p_amt = _as_float(row.get("pledge_amount")) or 0.0
        h_amt = _as_float(row.get("holding_amount")) or 0.0
        pledge_totals[_symbol(row)] += p_amt
        holding_totals[_symbol(row)] += h_amt

    symbols = [str(v) for v in params.get("universe_symbols", ())] or []
    outcomes = []
    target_symbols = symbols or list(pledge_totals)
    for sym in target_symbols:
        p_amt = pledge_totals.get(sym, 0.0)
        h_amt = holding_totals.get(sym, 0.0)
        if h_amt > 0:
            ratio = p_amt / h_amt
            status = "warn" if ratio >= threshold else "pass"
            reason = f"未解质押持股比例 {ratio:.2%}"
        elif p_amt > 0:
            status = "warn"
            reason = f"累计未解质押 {p_amt:.0f} 万股"
        else:
            status = "pass"
            reason = "无高风险未解质押记录"
        outcomes.append(_outcome({"symbol": sym}, "pledge_overhang", status, reason))
    return _result(outcomes)


__all__ = [
    "evaluate_consecutive_losses",
    "evaluate_consecutive_ocf_deficit",
    "evaluate_dedt_profit_loss",
    "evaluate_goodwill_observe",
    "evaluate_goodwill_overhang",
    "evaluate_high_leverage_insolvency",
    "evaluate_negative_equity",
    "evaluate_pledge_overhang",
    "evaluate_receivables_revenue_distortion",
    "evaluate_st_marked",
    "evaluate_too_new_listing",
]
