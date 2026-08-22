"""个股排雷端到端管线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.artifacts import (
    StockScreenArtifactPayload,
    StockScreenRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.stock_screen.decision import (
    RuleEvaluation,
    build_decision_tables,
    summarize_decisions,
)
from stock_analytics.pipelines.stock_screen.quality import build_manifest, build_quality_report
from stock_analytics.pipelines.stock_screen.rules import RULE_EVALUATORS, evaluate_rule
from stock_analytics.pipelines.stock_screen.scoring import compute_scores
from stock_analytics.pipelines.stock_screen.sources import (
    StockScreenSources,
    load_stock_screen_sources,
    resolve_as_of_date,
)
from stock_reporting.interpretation.stock_screen.config import (
    DEFAULT_CONFIG_PATH,
    RuleConfig,
    StockScreenConfig,
    load_stock_screen_config,
)
from stock_reporting.templates.stock_screen import (
    build_report_json,
    render_quality_report_markdown,
    render_report_markdown,
)

_RULE_DATASETS = {
    "st_marked": "stock_basic",
    "too_new_listing": "stock_basic",
    "penny_stock_face_value": "daily_basic",
    "illiquid_float": "stock_daily_bar",
    "consecutive_losses": "income",
    "negative_equity": "balancesheet",
    "goodwill_overhang": "balancesheet",
    "suspended": "stock_daily_bar",
    "forecast_plunge": "forecast",
    "holder_selloff": "stk_holdertrade",
    "goodwill_observe": "balancesheet",
    "northbound_drawdown": "hk_hold",
    "consecutive_limit_down": "limit_list_d",
    "margin_stress": "margin_detail",
}

_NOT_SUPPORTED_GATES = (
    {
        "rule_id": "audit_opinion",
        "scope": "all_market",
        "status": "not_supported",
        "note": "本地 income/balancesheet 无审计意见字段，未接入外部财报数据。",
    },
    {
        "rule_id": "regulatory_measures_and_inquiry",
        "scope": "all_market",
        "status": "registered_pending_backfill",
        "note": "理杏仁监管措施与交易所问询接口已注册，待回填至 Curated 后接入排雷规则。",
    },
    {
        "rule_id": "lockup_release",
        "scope": "all_market",
        "status": "registered_pending_backfill",
        "note": "TuShare share_float 与理杏仁限售解禁汇总接口已注册，待回填至 Curated 后接入排雷规则。",
    },
    {
        "rule_id": "litigation",
        "scope": "all_market",
        "status": "not_supported",
        "note": "本地没有诉讼专用接口；不使用公告标题关键词冒充诉讼事实。",
    },
)


@dataclass(frozen=True, slots=True)
class StockScreenRunResult:
    """一次个股排雷运行结果。"""

    as_of_date: date
    paths: StockScreenRunPaths
    manifest: dict[str, Any]
    sources: StockScreenSources
    tables: dict[str, pl.DataFrame]
    scores: dict[str, Any]
    report_markdown: str
    report_json: dict[str, Any]
    quality_report_markdown: str
    quality_report_json: dict[str, Any]


def run_stock_screen(
    *,
    target_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
    symbols: list[str] | None = None,
    catalogs: dict[str, Any] | None = None,
) -> StockScreenRunResult:
    """运行全市场或指定标的范围的个股排雷快照。"""
    config = load_stock_screen_config(config_path).with_artifact_root(output_root)
    if symbols is not None:
        config = config.with_symbols(symbols)
    configured_date = _parse_config_date(config.as_of)
    active_date = target_date or configured_date
    as_of_date = resolve_as_of_date(
        active_date,
        storage_dir=storage_dir,
        catalog=(catalogs or {}).get("tushare"),
    )
    sources = load_stock_screen_sources(
        config,
        as_of_date,
        storage_dir=storage_dir,
        catalogs=catalogs,
    )
    universe = _build_universe(sources.get("stock_basic"), config.symbols, as_of_date)
    evaluations, missing_gates, data_gaps = _evaluate_rules(
        config,
        sources,
        universe,
        as_of_date,
    )
    tables = build_decision_tables(
        universe,
        evaluations,
        as_of_date=as_of_date.isoformat(),
    )
    scored = (
        compute_scores(tables.get("passed", pl.DataFrame()), sources, as_of_date)
        if config.scoring.enabled
        else pl.DataFrame()
    )
    artifact_tables = _limit_artifact_tables(tables, config)
    if not scored.is_empty():
        artifact_tables = {**artifact_tables, "scored": scored.head(config.scoring.top_n)}
    data_gaps = _deduplicate_gaps([*sources.data_gaps, *data_gaps])
    scores = summarize_decisions(
        tables,
        population_size=universe.height,
        data_gaps=data_gaps,
        missing_gates=missing_gates,
    )
    if not scored.is_empty():
        scores["scored_top_count"] = scored.height
        scores["scored_median"] = round(float(scored.get_column("composite_score").median()), 1)  # type: ignore[arg-type]
        scores["scored_top_symbols"] = scored.head(10).get_column("symbol").to_list()
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = build_manifest(config, as_of_date, paths, scores)
    quality_report_json = build_quality_report(config, as_of_date, sources, scores)
    quality_report_markdown = render_quality_report_markdown(quality_report_json)
    report_json = build_report_json(
        config=config,
        manifest=manifest,
        summary=scores,
        tables=artifact_tables,
    )
    report_markdown = render_report_markdown(
        config=config,
        manifest=manifest,
        summary=scores,
        tables=artifact_tables,
    )
    write_artifacts(
        paths,
        StockScreenArtifactPayload(
            manifest=manifest,
            excluded=artifact_tables["excluded"],
            warned=artifact_tables["warned"],
            passed=artifact_tables["passed"],
            scored=scored,
            scores=scores,
            report_markdown=report_markdown,
            report_json=report_json,
            quality_report_markdown=quality_report_markdown,
            quality_report_json=quality_report_json,
        ),
        update_latest=update_latest,
    )
    return StockScreenRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        sources=sources,
        tables=tables,
        scores=scores,
        report_markdown=report_markdown,
        report_json=report_json,
        quality_report_markdown=quality_report_markdown,
        quality_report_json=quality_report_json,
    )


def _evaluate_rules(
    config: StockScreenConfig,
    sources: StockScreenSources,
    universe: pl.DataFrame,
    as_of_date: date,
) -> tuple[list[RuleEvaluation], list[dict[str, Any]], list[dict[str, str]]]:
    evaluations: list[RuleEvaluation] = []
    missing_gates: list[dict[str, Any]] = [dict(item) for item in _NOT_SUPPORTED_GATES]
    data_gaps: list[dict[str, str]] = []
    for category, rules in (
        ("hard_exclusion", config.hard_exclusion),
        ("yellow_warn", config.yellow_warn),
    ):
        for rule in rules:
            if not rule.enabled:
                missing_gates.append(_missing_rule(rule, "disabled"))
                continue
            input_frame = _rule_input(rule, sources, universe, as_of_date)
            if input_frame.is_empty() and rule.rule_id not in {"st_marked", "too_new_listing"}:
                missing_gates.append(_missing_rule(rule, "data_unavailable"))
                data_gaps.append(
                    {
                        "data_source": "tushare",
                        "dataset": _RULE_DATASETS.get(rule.rule_id, "unknown"),
                        "status": "missing_for_rule",
                        "note": rule.note,
                    }
                )
                continue
            params = {
                **rule.params,
                "as_of_date": as_of_date,
                "universe_symbols": universe.get_column("symbol").to_list()
                if "symbol" in universe.columns
                else [],
            }
            result = evaluate_rule(rule.rule_id, input_frame, params)
            if rule.rule_id not in RULE_EVALUATORS:
                missing_gates.append(_missing_rule(rule, "not_supported"))
                continue
            evaluations.append(RuleEvaluation(rule=rule, category=category, frame=result))
    return evaluations, missing_gates, data_gaps


def _rule_input(
    rule: RuleConfig,
    sources: StockScreenSources,
    universe: pl.DataFrame,
    as_of_date: date,
) -> pl.DataFrame:
    if rule.rule_id in {"st_marked", "too_new_listing"}:
        return universe
    if rule.rule_id == "suspended":
        return _suspension_input(sources, as_of_date)
    dataset = _RULE_DATASETS.get(rule.rule_id)
    frame = sources.get(dataset or "")
    if dataset in {"daily_basic", "stock_daily_bar"}:
        return _at_as_of(frame, "trade_date", as_of_date)
    return frame


def _build_universe(
    frame: pl.DataFrame,
    symbols: tuple[str, ...],
    as_of_date: date,
) -> pl.DataFrame:
    if frame.is_empty() or "symbol" not in frame.columns:
        return pl.DataFrame(
            schema={
                "symbol": pl.String,
                "name": pl.String,
                "industry": pl.String,
                "list_date": pl.Date,
                "market": pl.String,
            }
        )
    result = frame
    if symbols:
        result = result.filter(pl.col("symbol").is_in(list(symbols)))
    if "list_status" in result.columns:
        result = result.filter(
            pl.col("list_status")
            .cast(pl.String, strict=False)
            .str.to_uppercase()
            .is_in(["L", "上市"])
        )
    if "list_date" in result.columns:
        result = result.filter(pl.col("list_date").is_null() | (pl.col("list_date") <= as_of_date))
    if "delist_date" in result.columns:
        result = result.filter(
            pl.col("delist_date").is_null() | (pl.col("delist_date") > as_of_date)
        )
    if "industry" not in result.columns:
        result = result.with_columns(
            pl.col("industry_name").cast(pl.String, strict=False).alias("industry")
            if "industry_name" in result.columns
            else pl.lit(None, dtype=pl.String).alias("industry")
        )
    return result.unique(subset=["symbol"], keep="last")


def _suspension_input(sources: StockScreenSources, as_of_date: date) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    bars = sources.get("stock_daily_bar")
    if not bars.is_empty():
        frames.append(
            bars.select([column for column in ("symbol", "trade_date") if column in bars.columns])
        )
    suspensions = sources.get("suspend_d")
    if not suspensions.is_empty():
        selected = suspensions
        if "suspend_date" not in selected.columns and "trade_date" in selected.columns:
            selected = selected.with_columns(pl.col("trade_date").alias("suspend_date"))
        selected = selected.select(
            [
                column
                for column in ("symbol", "trade_date", "suspend_date", "suspend_type")
                if column in selected.columns
            ]
        )
        frames.append(selected)
    if not frames:
        return pl.DataFrame()
    combined = pl.concat(frames, how="diagonal_relaxed")
    if "trade_date" in combined.columns:
        combined = combined.filter(
            pl.col("trade_date").is_null() | (pl.col("trade_date") <= as_of_date)
        )
    if "suspend_date" in combined.columns:
        combined = combined.filter(
            pl.col("suspend_date").is_null() | (pl.col("suspend_date") <= as_of_date)
        )
    return combined


def _at_as_of(frame: pl.DataFrame, date_column: str, as_of_date: date) -> pl.DataFrame:
    if frame.is_empty() or date_column not in frame.columns:
        return pl.DataFrame()
    return frame.filter(pl.col(date_column) == as_of_date)


def _limit_artifact_tables(
    tables: dict[str, pl.DataFrame], config: StockScreenConfig
) -> dict[str, pl.DataFrame]:
    """按配置限制清单展示行数，决策摘要仍使用全量表。"""
    return {
        **tables,
        "warned": tables["warned"].head(config.output.max_warn_rows),
        "passed": tables["passed"].head(config.output.top_passed),
    }


def _parse_config_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _missing_rule(rule: RuleConfig, status: str) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "scope": rule.scope,
        "status": status,
        "note": rule.note,
    }


def _deduplicate_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result = []
    for gap in gaps:
        key = (str(gap.get("data_source")), str(gap.get("dataset")), str(gap.get("status")))
        if key in seen:
            continue
        seen.add(key)
        result.append(gap)
    return result


__all__ = ["StockScreenRunResult", "run_stock_screen"]
