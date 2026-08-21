"""排雷规则共享的数据整理与结果构造函数。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from itertools import pairwise
from typing import Any

import polars as pl

RuleEvaluator = Callable[[pl.DataFrame, dict[str, Any]], pl.DataFrame]

_RESULT_SCHEMA = {
    "symbol": pl.String,
    "rule_id": pl.String,
    "status": pl.String,
    "reason": pl.String,
    "note": pl.String,
    "value": pl.Float64,
}


def rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """返回带有有效标的代码的字典行。"""
    return [row for row in frame.to_dicts() if symbol(row)]


def latest_rows(frame: pl.DataFrame, date_column: str = "ann_date") -> list[dict[str, Any]]:
    """按标的保留日期列最新一行。"""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(frame):
        grouped[symbol(row)].append(row)
    result = []
    for values in grouped.values():
        values.sort(key=lambda item: as_date(item.get(date_column)) or date.min)
        result.append(values[-1])
    return result


def count_results(counts: dict[str, int], rule_id: str, threshold: int, label: str) -> pl.DataFrame:
    """将事件计数转换为规则结果。"""
    return result_frame(
        outcome(
            {"symbol": item},
            rule_id,
            "warn" if count >= threshold else "pass",
            f"{label} {count} 笔",
        )
        for item, count in counts.items()
    )


def result_frame(outcomes: Any) -> pl.DataFrame:
    """构造统一规则结果表。"""
    values = list(outcomes)
    if not values:
        return pl.DataFrame(schema=_RESULT_SCHEMA)
    return (
        pl.DataFrame(values)
        .select(list(_RESULT_SCHEMA))
        .with_columns(
            pl.col("symbol").cast(pl.String, strict=False),
            pl.col("rule_id").cast(pl.String, strict=False),
            pl.col("status").cast(pl.String, strict=False),
            pl.col("reason").cast(pl.String, strict=False),
            pl.col("note").cast(pl.String, strict=False),
            pl.col("value").cast(pl.Float64, strict=False),
        )
    )


def not_evaluated(rows_frame: pl.DataFrame, rule_id: str, reason: str) -> pl.DataFrame:
    """返回数据字段缺失的规则结果。"""
    return result_frame(outcome(row, rule_id, "not_evaluated", reason) for row in rows(rows_frame))


def outcome(row: dict[str, Any], rule_id: str, status: str, reason: str) -> dict[str, Any]:
    """构造一条规则命中结果。"""
    return {
        "symbol": symbol(row),
        "rule_id": rule_id,
        "status": status,
        "reason": reason,
        "note": reason,
        "value": None,
    }


def symbol(row: dict[str, Any]) -> str:
    """读取标准标的代码。"""
    return str(row.get("symbol") or row.get("ts_code") or "").strip()


def unique_symbols(frame: pl.DataFrame) -> list[str]:
    """返回去重后的标的代码。"""
    return list(dict.fromkeys(symbol(row) for row in rows(frame)))


def first_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """返回候选字段中第一个存在的列。"""
    return next((column for column in candidates if column in frame.columns), None)


def as_float(value: object) -> float | None:
    """安全转换数值。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def as_date(value: object) -> date | None:
    """安全转换 YYYYMMDD/YYYY-MM-DD 日期。"""
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def as_of(params: dict[str, Any], frame: pl.DataFrame, date_column: str) -> date:
    """读取显式基准日，缺失时回退到输入数据最大日期。"""
    explicit = as_date(params.get("as_of_date"))
    if explicit is not None:
        return explicit
    if date_column in frame.columns:
        values = [as_date(value) for value in frame.get_column(date_column).to_list()]
        valid = [value for value in values if value is not None]
        if valid:
            return max(valid)
    return date.today()


def is_limit_down(row: dict[str, Any]) -> bool:
    """按 limit 字段或跌幅识别跌停事件。"""
    for column in ("limit", "limit_type"):
        value = str(row.get(column) or "").strip().upper()
        if value:
            return value in {"D", "DOWN", "跌停", "LIMIT_DOWN"} or "DOWN" in value
    pct_chg = as_float(row.get("pct_chg"))
    return pct_chg is not None and pct_chg <= -9.5


def max_consecutive_run(values: list[date]) -> int:
    """按交易日事件日期计算最长连续运行长度。"""
    if not values:
        return 0
    maximum = current = 1
    for previous, value in pairwise(values):
        if (value - previous).days <= 4:
            current += 1
        else:
            current = 1
        maximum = max(maximum, current)
    return maximum


__all__ = [
    "RuleEvaluator",
    "as_date",
    "as_float",
    "as_of",
    "count_results",
    "first_column",
    "is_limit_down",
    "latest_rows",
    "max_consecutive_run",
    "not_evaluated",
    "outcome",
    "result_frame",
    "rows",
    "symbol",
    "unique_symbols",
]
