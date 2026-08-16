"""市场温度计产物管线编排。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from stock.analytics.data_quality import build_quality_report, render_quality_report_markdown
from stock.analytics.market_temperature.artifacts import (
    MarketTemperatureArtifactPayload,
    MarketTemperatureRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock.analytics.market_temperature.config import (
    DEFAULT_CONFIG_PATH,
    MarketTemperatureConfig,
    load_market_temperature_config,
)
from stock.analytics.market_temperature.facts import collect_facts, resolve_trade_window
from stock.analytics.market_temperature.scoring import build_scores
from stock.analytics.market_temperature.templates import (
    build_report_json,
    render_human_report_markdown,
    render_report_markdown,
)

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl


@dataclass(frozen=True, slots=True)
class MarketTemperatureRunResult:
    """市场温度计一次运行结果。"""

    as_of_date: date
    paths: MarketTemperatureRunPaths
    manifest: dict[str, Any]
    facts: pl.DataFrame
    scores: dict[str, Any]
    report_markdown: str
    human_report_markdown: str
    report_json: dict[str, Any]
    quality_report_markdown: str
    quality_report_json: dict[str, Any]


def run_market_temperature(  # noqa: PLR0913
    *,
    target_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    collect_metric_values: bool | None = None,
    storage_dir: Path | str | None = None,
) -> MarketTemperatureRunResult:
    """运行市场温度计事实采集、评分结构生成与产物写入。"""
    config = load_market_temperature_config(config_path).with_artifact_root(output_root)
    as_of_date, trade_dates = resolve_trade_window(config, target_date, storage_dir=storage_dir)
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = _build_manifest(config, as_of_date, trade_dates, paths)
    facts = collect_facts(
        config,
        as_of_date=as_of_date,
        trade_dates=trade_dates,
        storage_dir=storage_dir,
        collect_metric_values=collect_metric_values,
    )
    scores = build_scores(config, as_of_date=as_of_date, facts=facts)
    quality_report_json = build_quality_report(
        title=config.title,
        manifest=manifest,
        facts=facts,
        datasets=config.datasets,
        primary_data_source="tushare",
        primary_dataset="stock_daily_bar",
        main_window=config.main_window,
        short_windows=config.short_windows,
        period_note="六维主温度按最近已落盘 A 股交易日取窗口；短线窗口只作节奏观察。",
    )
    quality_report_markdown = render_quality_report_markdown(quality_report_json)
    report_json = build_report_json(config=config, manifest=manifest, scores=scores, facts=facts)
    report_markdown = render_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
    )
    human_report_markdown = render_human_report_markdown(
        config=config,
        manifest=manifest,
        scores=scores,
        facts=facts,
    )
    write_artifacts(
        paths,
        MarketTemperatureArtifactPayload(
            manifest=manifest,
            facts=facts,
            scores=scores,
            report_markdown=report_markdown,
            report_json=report_json,
            human_report_markdown=human_report_markdown,
            quality_report_markdown=quality_report_markdown,
            quality_report_json=quality_report_json,
        ),
        update_latest=update_latest,
    )
    return MarketTemperatureRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        facts=facts,
        scores=scores,
        report_markdown=report_markdown,
        human_report_markdown=human_report_markdown,
        report_json=report_json,
        quality_report_markdown=quality_report_markdown,
        quality_report_json=quality_report_json,
    )


def _build_manifest(
    config: MarketTemperatureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    paths: MarketTemperatureRunPaths,
) -> dict[str, Any]:
    run_id = paths.run_dir.name
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "main_window": config.main_window,
        "short_windows": list(config.short_windows),
        "trade_dates": [value.isoformat() for value in trade_dates],
        "artifact_root": str(paths.root),
        "files": {
            "manifest": paths.manifest.name,
            "facts": paths.facts.name,
            "scores": paths.scores.name,
            "report_md": paths.report_md.name,
            "report_json": paths.report_json.name,
            "human_report_md": paths.human_report_md.name,
            "quality_report_md": paths.quality_report_md.name,
            "quality_report_json": paths.quality_report_json.name,
        },
    }
