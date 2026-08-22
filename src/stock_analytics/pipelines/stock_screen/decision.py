"""个股排雷规则结果合并与三路决策。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import polars as pl

from stock_reporting.interpretation.stock_screen.config import RuleConfig


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """单条规则的执行结果。"""

    rule: RuleConfig
    category: str
    frame: pl.DataFrame


def build_decision_tables(
    universe: pl.DataFrame,
    evaluations: Iterable[RuleEvaluation],
    *,
    warning_upgrade_count: int = 3,
    as_of_date: str | None = None,
) -> dict[str, pl.DataFrame]:
    """合并逐条规则结果并生成 excluded/warned/passed 三张表。"""
    evaluation_list = list(evaluations)
    hard_failures = {
        str(result.get("symbol") or "")
        for evaluation in evaluation_list
        if evaluation.category == "hard_exclusion"
        for result in evaluation.frame.to_dicts()
        if result.get("status") == "fail"
    }
    hard_missing = {
        str(result.get("symbol") or "")
        for evaluation in evaluation_list
        if evaluation.category == "hard_exclusion"
        for result in evaluation.frame.to_dicts()
        if result.get("status") == "not_evaluated"
    }
    base_rows = _universe_rows(universe)
    by_symbol: dict[str, dict[str, Any]] = {
        row["symbol"]: {
            "symbol": row["symbol"],
            "name": row.get("name"),
            "industry": row.get("industry") or row.get("industry_name"),
            "list_date": row.get("list_date"),
            "market": row.get("market"),
            "reasons": [],
            "rule_ids": [],
            "warn_count": 0,
            "missing_rules": [],
        }
        for row in base_rows
    }
    for evaluation in evaluation_list:
        note = evaluation.rule.note
        for result in evaluation.frame.to_dicts():
            symbol = str(result.get("symbol") or "")
            if symbol not in by_symbol:
                continue
            status = str(result.get("status") or "not_evaluated")
            if status == "not_evaluated":
                by_symbol[symbol]["missing_rules"].append(evaluation.rule.rule_id)
                continue
            if status not in {"fail", "warn"}:
                continue
            reason = str(result.get("reason") or evaluation.rule.rule_id)
            text = f"{evaluation.rule.rule_id}: {reason}"
            if note:
                text = f"{text}（{note}）"
            by_symbol[symbol]["reasons"].append(text)
            by_symbol[symbol]["rule_ids"].append(evaluation.rule.rule_id)
            if status == "warn":
                by_symbol[symbol]["warn_count"] += 1

    output_rows: list[dict[str, Any]] = []
    for row in by_symbol.values():
        row["rule_ids"] = list(dict.fromkeys(row["rule_ids"]))
        row["reasons"] = list(dict.fromkeys(row["reasons"]))
        row["missing_rules"] = list(dict.fromkeys(row["missing_rules"]))
        if row["symbol"] in hard_failures:
            level = "excluded"
        elif row["warn_count"] >= warning_upgrade_count:
            level = "excluded"
            row["reasons"].append(
                f"warn_count={row['warn_count']} 达到 {warning_upgrade_count}，升级为临时排除"
            )
        elif row["warn_count"]:
            level = "warned"
        elif row["symbol"] in hard_missing:
            level = "warned"
            row["reasons"].append("核心排雷规则数据缺失未评估，降级观察")
        else:
            level = "passed"
        row["level"] = level
        row["note"] = _build_note(row, as_of_date)
        output_rows.append(row)

    frame = pl.DataFrame(output_rows) if output_rows else _empty_output()
    if not frame.is_empty():
        frame = frame.with_columns(
            pl.col("list_date").cast(pl.String, strict=False),
            pl.col("reasons").cast(pl.List(pl.String), strict=False),
            pl.col("rule_ids").cast(pl.List(pl.String), strict=False),
            pl.col("missing_rules").cast(pl.List(pl.String), strict=False),
        )
    return {
        "excluded": frame.filter(pl.col("level") == "excluded"),
        "warned": frame.filter(pl.col("level") == "warned"),
        "passed": frame.filter(pl.col("level") == "passed"),
        "all": frame,
    }


def summarize_decisions(
    tables: Mapping[str, pl.DataFrame],
    *,
    population_size: int,
    data_gaps: list[dict[str, Any]],
    missing_gates: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造 JSON 可序列化的决策摘要。"""
    excluded = tables.get("excluded", pl.DataFrame())
    warned = tables.get("warned", pl.DataFrame())
    passed = tables.get("passed", pl.DataFrame())
    return {
        "population_size": population_size,
        "excluded_count": excluded.height,
        "warned_count": warned.height,
        "passed_count": passed.height,
        "data_gaps": data_gaps,
        "missing_gates": missing_gates,
        "rule_version": "stock_screen.v1",
    }


def _universe_rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    if frame.is_empty() or "symbol" not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in frame.to_dicts():
        symbol = str(row.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        rows.append({**row, "symbol": symbol})
    return rows


def _build_note(row: dict[str, Any], as_of_date: str | None) -> str:
    pieces = []
    if as_of_date:
        pieces.append(f"数据基准日 {as_of_date}")
    if row["missing_rules"]:
        pieces.append(f"未评估规则: {','.join(row['missing_rules'])}")
    if not row["reasons"] and not pieces:
        return "无命中规则"
    return "；".join(pieces) or "命中规则见 reasons"


def _empty_output() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.String,
            "name": pl.String,
            "industry": pl.String,
            "list_date": pl.String,
            "market": pl.String,
            "reasons": pl.List(pl.String),
            "rule_ids": pl.List(pl.String),
            "level": pl.String,
            "note": pl.String,
            "warn_count": pl.Int64,
            "missing_rules": pl.List(pl.String),
        }
    )


__all__ = [
    "RuleEvaluation",
    "build_decision_tables",
    "summarize_decisions",
]
