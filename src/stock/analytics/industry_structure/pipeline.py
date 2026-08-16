"""行业结构分析产物管线编排。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from stock.analytics.industry_structure.artifacts import (
    IndustryStructureArtifactPayload,
    IndustryStructureRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock.analytics.industry_structure.config import (
    DEFAULT_CONFIG_PATH,
    IndustryStructureConfig,
    load_industry_structure_config,
)
from stock.analytics.industry_structure.facts import collect_facts, resolve_trade_window
from stock.analytics.industry_structure.panel import build_industry_panel
from stock.analytics.industry_structure.scoring import score_industry_panel
from stock.analytics.industry_structure.templates import (
    build_report_json,
    render_human_report_markdown,
    render_report_markdown,
)

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl


@dataclass(frozen=True, slots=True)
class IndustryStructureRunResult:
    """行业结构分析一次运行结果。"""

    as_of_date: date
    paths: IndustryStructureRunPaths
    manifest: dict[str, Any]
    facts: pl.DataFrame
    industry_panel: pl.DataFrame
    scores: dict[str, Any]
    report_markdown: str
    human_report_markdown: str
    report_json: dict[str, Any]


def run_industry_structure(
    *,
    target_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
) -> IndustryStructureRunResult:
    """运行行业结构事实采集、评分结构生成与产物写入。"""
    config = load_industry_structure_config(config_path).with_artifact_root(output_root)
    as_of_date, trade_dates = resolve_trade_window(config, target_date, storage_dir=storage_dir)
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = _build_manifest(config, as_of_date, trade_dates, paths)
    base_panel = build_industry_panel(
        config,
        as_of_date=as_of_date,
        trade_dates=trade_dates,
        storage_dir=storage_dir,
    )
    industry_panel, scores = score_industry_panel(config, base_panel)
    facts = collect_facts(
        config,
        as_of_date=as_of_date,
        trade_dates=trade_dates,
        industry_panel=industry_panel,
        storage_dir=storage_dir,
    )
    report_json = build_report_json(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
        industry_panel=industry_panel,
    )
    report_markdown = render_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
        industry_panel=industry_panel,
    )
    human_report_markdown = render_human_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
        industry_panel=industry_panel,
    )
    write_artifacts(
        paths,
        IndustryStructureArtifactPayload(
            manifest=manifest,
            facts=facts,
            industry_panel=industry_panel,
            scores=scores,
            report_markdown=report_markdown,
            report_json=report_json,
            human_report_markdown=human_report_markdown,
        ),
        update_latest=update_latest,
    )
    return IndustryStructureRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        facts=facts,
        industry_panel=industry_panel,
        scores=scores,
        report_markdown=report_markdown,
        human_report_markdown=human_report_markdown,
        report_json=report_json,
    )


def _build_manifest(
    config: IndustryStructureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    paths: IndustryStructureRunPaths,
) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "run_id": paths.run_dir.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "main_window": config.main_window,
        "short_windows": list(config.short_windows),
        "medium_windows": list(config.medium_windows),
        "classification": config.classification,
        "benchmark": config.benchmark,
        "trade_dates": [value.isoformat() for value in trade_dates],
        "artifact_root": str(paths.root),
        "files": {
            "manifest": paths.manifest.name,
            "facts": paths.facts.name,
            "industry_panel": paths.industry_panel.name,
            "scores": paths.scores.name,
            "report_md": paths.report_md.name,
            "report_json": paths.report_json.name,
            "human_report_md": paths.human_report_md.name,
        },
    }
