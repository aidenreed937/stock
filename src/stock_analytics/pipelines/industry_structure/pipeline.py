"""行业结构分析产物管线编排。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from stock_analytics.data_quality import build_quality_report
from stock_analytics.pipelines.industry_structure.artifacts import (
    IndustryStructureArtifactPayload,
    IndustryStructureRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.industry_structure.facts import collect_facts, resolve_trade_window
from stock_analytics.pipelines.industry_structure.panel import load_industry_panel_daily
from stock_analytics.pipelines.industry_structure.scoring import score_industry_panel
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_reporting.interpretation.industry_structure.config import (
    DEFAULT_CONFIG_PATH,
    IndustryStructureConfig,
    load_industry_structure_config,
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
    quality_report_markdown: str
    quality_report_json: dict[str, Any]


def run_industry_structure(
    *,
    target_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    storage_dir: Path | str | None = None,
    dataset_cache: DatasetFrameCache | None = None,
    trade_dates: tuple[date, ...] | None = None,
) -> IndustryStructureRunResult:
    """运行行业结构事实采集、评分结构生成与产物写入。"""
    config = load_industry_structure_config(config_path).with_artifact_root(output_root)
    if trade_dates is None:
        as_of_date, resolved_trade_dates = resolve_trade_window(
            config,
            target_date,
            storage_dir=storage_dir,
            dataset_cache=dataset_cache,
        )
    else:
        resolved_trade_dates = tuple(
            sorted(value for value in trade_dates if target_date is None or value <= target_date)
        )[-max(config.windows, default=config.main_window) :]
        if not resolved_trade_dates:
            raise ValueError("传入的行业结构交易日窗口为空")
        as_of_date = target_date or resolved_trade_dates[-1]
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = _build_manifest(config, as_of_date, resolved_trade_dates, paths)
    base_panel = load_industry_panel_daily(as_of_date=as_of_date, storage_dir=storage_dir)
    industry_panel, scores = score_industry_panel(config, base_panel)
    facts = collect_facts(
        config,
        as_of_date=as_of_date,
        trade_dates=resolved_trade_dates,
        industry_panel=industry_panel,
        storage_dir=storage_dir,
        dataset_cache=dataset_cache,
    )
    quality_report_json = build_quality_report(
        title=config.title,
        manifest=manifest,
        facts=facts,
        datasets=config.datasets,
        primary_data_source="tushare",
        primary_dataset="sw_daily",
        main_window=config.main_window,
        short_windows=config.short_windows,
        medium_windows=config.medium_windows,
        period_note="行业结构主窗口按最近已落盘申万行业交易日取窗口；60/120 日只作中期确认。",
    )
    from stock_reporting.core.quality import render_quality_report_markdown
    from stock_reporting.templates.industry_structure import (
        build_report_json,
        render_human_report_markdown,
        render_report_markdown,
    )

    quality_report_markdown = render_quality_report_markdown(quality_report_json)
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
            quality_report_markdown=quality_report_markdown,
            quality_report_json=quality_report_json,
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
        quality_report_markdown=quality_report_markdown,
        quality_report_json=quality_report_json,
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
            "quality_report_md": paths.quality_report_md.name,
            "quality_report_json": paths.quality_report_json.name,
        },
    }
