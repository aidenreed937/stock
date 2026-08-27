"""从已落盘市场温度、行业结构、投资者简报和量化投研简报生成跨周期复盘。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from stock_analytics.pipelines.artifacts import select_artifact_run_dir
from stock_analytics.pipelines.market_cycle_review_analysis import (
    DIMENSION_KEYS,
    FACT_KEYS,
    _build_payload,
)
from stock_analytics.pipelines.market_cycle_review_render import _render_markdown
from stock_analytics.pipelines.market_temperature.scoring import (
    _fast_slow_temperatures,
)
from stock_analytics.pipelines.report_consistency import ConsistencyValidator


@dataclass(frozen=True, slots=True)
class ArtifactDirs:
    market: Path
    industry: Path
    brief: Path
    quant: Path | None = None


@dataclass(frozen=True, slots=True)
class MarketCycleReviewRunResult:
    """市场跨周期复盘一次运行的结果。"""

    dates: tuple[str, ...]
    payload: dict[str, Any]
    paths: dict[str, Path]


def run_market_cycle_review(
    *,
    start: str,
    end: str,
    analytics_root: Path | str = "data/analytics",
    output_root: Path | str = "data/analytics/market_cycle_review",
    skip_consistency: bool = False,
    update_latest: bool = True,
) -> MarketCycleReviewRunResult:
    """从已落盘分析产物生成市场跨周期复盘。"""
    analytics_path = Path(analytics_root)
    dates = _resolve_dates(start, end, analytics_path)
    if not dates:
        raise FileNotFoundError(f"没有找到可复盘的日期: {start} ~ {end}")

    consistency_status = "skipped" if skip_consistency else "passed"
    if not skip_consistency:
        consistency = ConsistencyValidator(analytics_path).validate_dates(dates)
        if consistency.status != "passed":
            details = "; ".join(
                f"{issue.as_of_date} {issue.artifact}: {issue.message}"
                for issue in consistency.errors[:20]
            )
            raise RuntimeError(f"report_consistency 未通过，停止生成跨周期复盘: {details}")

    market_rows, panel_rows = _load_rows(analytics_path, dates)
    payload = _build_payload(
        dates,
        market_rows,
        panel_rows,
        consistency_status=consistency_status,
    )
    markdown = _render_markdown(payload)
    paths = _write_artifacts(Path(output_root), payload, markdown, update_latest=update_latest)
    return MarketCycleReviewRunResult(tuple(dates), payload, paths)


def _resolve_dates(start: str, end: str, analytics_root: Path) -> list[str]:
    dates = ConsistencyValidator(analytics_root).available_dates(start, end)
    return [value for value in dates if start <= value <= end]


def _load_rows(
    analytics_root: Path,
    dates: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_rows: list[dict[str, Any]] = []
    panel_rows: list[dict[str, Any]] = []
    for as_of_date in dates:
        dirs = _artifact_dirs(analytics_root, as_of_date)
        market_rows.append(_load_market_row(dirs, as_of_date))
        panel_rows.extend(_load_panel_rows(dirs, as_of_date))
    return market_rows, panel_rows


def _artifact_dirs(root: Path, as_of_date: str) -> ArtifactDirs:
    return ArtifactDirs(
        market=_latest_run_dir(root / "market_temperature", as_of_date),
        industry=_latest_run_dir(root / "industry_structure", as_of_date),
        brief=_latest_run_dir(root / "investor_brief", as_of_date),
        quant=_optional_latest_run_dir(root / "quant_brief", as_of_date),
    )


def _latest_run_dir(root: Path, as_of_date: str) -> Path:
    run_dir = select_artifact_run_dir(root, as_of_date=as_of_date)
    if run_dir is None:
        raise FileNotFoundError(f"未找到产物目录: {root / 'runs' / f'as_of={as_of_date}'}")
    return run_dir


def _optional_latest_run_dir(root: Path, as_of_date: str) -> Path | None:
    return select_artifact_run_dir(root, as_of_date=as_of_date)


def _add_fast_slow_fields(
    scores: dict[str, Any],
    row: dict[str, Any],
) -> None:
    """为 daily_rows 补充快/慢温度与背离字段。

    优先读 scores.fast_slow（新运行产物）；旧产物缺失该块时，用
    scoring 的权威合成函数按维度权重回退计算，保证跨周期复盘对历史
    产物向后兼容且口径一致（权重与分档阈值只维护在 scoring 一处）。
    """
    fast_slow = scores.get("fast_slow")
    if isinstance(fast_slow, dict) and fast_slow.get("status") == "ready":
        row["fast_temperature"] = fast_slow.get("fast_temperature")
        row["slow_temperature"] = fast_slow.get("slow_temperature")
        row["divergence"] = fast_slow.get("divergence")
        row["divergence_level"] = fast_slow.get("divergence_level")
        return
    computed = _fast_slow_temperatures(scores.get("dimensions", []))
    if computed.get("status") != "ready":
        return
    row["fast_temperature"] = computed.get("fast_temperature")
    row["slow_temperature"] = computed.get("slow_temperature")
    row["divergence"] = computed.get("divergence")
    row["divergence_level"] = computed.get("divergence_level")


def _load_market_row(dirs: ArtifactDirs, as_of_date: str) -> dict[str, Any]:
    scores = _read_json(dirs.market / "scores.json")
    industry_scores = _read_json(dirs.industry / "scores.json")
    brief = _read_json(dirs.brief / "brief_report.json")
    quant = _read_json(dirs.quant / "brief_report.json") if dirs.quant is not None else {}
    facts = pl.read_parquet(dirs.market / "facts.parquet")
    fact_values = {
        row["metric_id"]: row.get("value_float") for row in facts.to_dicts() if row.get("metric_id")
    }
    dimensions = {
        row["dimension_id"]: row.get("temperature")
        for row in scores.get("dimensions", [])
        if row.get("dimension_id")
    }
    health = industry_scores.get("structure_health", {})
    row: dict[str, Any] = {
        "date": as_of_date,
        "composite": scores.get("composite", {}).get("temperature"),
        "risk_level": scores.get("systemic_risk", {}).get("level"),
        "structure_health": health.get("level"),
        "positive_return_20d_count": health.get("positive_return_20d_count"),
        "positive_return_60d_count": health.get("positive_return_60d_count"),
        "crowded_industry_count": health.get("crowded_industry_count"),
        "strong_trend_count": health.get("strong_trend_count"),
        "candidate_industries": _names(brief.get("candidate_industries", [])),
        "risk_industries": _names(brief.get("risk_industries", [])),
        "lagging_industries": _names(brief.get("lagging_industries", [])),
        "quant_nature": quant.get("nature", {}).get("nature_type"),
        "quant_veto_status": quant.get("veto", {}).get("status"),
        "quant_brief_available": bool(quant),
        "quant_top5pct_share": quant.get("veto", {})
        .get("top5pct", {})
        .get("value", fact_values.get("amount_top_5pct_share")),
        "quant_priority_industries": _names(quant.get("sector", {}).get("priority", [])),
        "quant_avoid_industries": _names(quant.get("sector", {}).get("avoid", [])),
    }
    row.update({key: dimensions.get(key) for key in DIMENSION_KEYS})
    _add_fast_slow_fields(scores, row)
    sentiment_row: dict[str, Any] = next(
        (item for item in scores.get("dimensions", []) if item.get("dimension_id") == "sentiment"),
        {},
    )
    subgroups = sentiment_row.get("subgroups", {})
    if isinstance(subgroups, dict):
        row["sentiment_activity"] = subgroups.get("activity")
        row["sentiment_slow"] = subgroups.get("slow")
    row["sentiment_temperature_source"] = sentiment_row.get("temperature_source")
    row.update({key: fact_values.get(key) for key in FACT_KEYS})
    return row


def _load_panel_rows(dirs: ArtifactDirs, as_of_date: str) -> list[dict[str, Any]]:
    panel = pl.read_parquet(dirs.industry / "industry_panel.parquet")
    if "structure_rank" not in panel.columns:
        panel = panel.sort("structure_score", descending=True).with_row_index(
            "structure_rank",
            offset=1,
        )
    keys = (
        "industry_name",
        "structure_rank",
        "structure_score",
        "return_20d",
        "return_60d",
        "tcr",
        "crowding_temperature",
        "tags",
    )
    return [{"date": as_of_date, **{key: row.get(key) for key in keys}} for row in panel.to_dicts()]


def _write_artifacts(
    output_root: Path,
    payload: dict[str, Any],
    markdown: str,
    *,
    update_latest: bool,
) -> dict[str, Path]:
    run_id = f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = (
        output_root / "runs" / f"start={payload['start_date']}_end={payload['end_date']}" / run_id
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "review.json"
    markdown_path = run_dir / "review.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    if update_latest:
        latest_dir = output_root / "latest"
        latest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, latest_dir / json_path.name)
        shutil.copy2(markdown_path, latest_dir / markdown_path.name)
    return {"json": json_path, "markdown": markdown_path}


def _read_json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["industry_name"]) for row in rows if row.get("industry_name")]
