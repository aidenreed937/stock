"""市场温度计产物管线编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_analytics.data_quality import build_quality_report
from stock_analytics.pipelines.market_temperature.artifacts import (
    MarketTemperatureArtifactPayload,
    MarketTemperatureRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.facts import (
    collect_facts,
    resolve_external_cutoff_date,
    resolve_trade_window,
)
from stock_analytics.pipelines.market_temperature.scoring import build_scores
from stock_reporting.interpretation.market_temperature.config import (
    DEFAULT_CONFIG_PATH,
    MarketTemperatureConfig,
    load_market_temperature_config,
)

if TYPE_CHECKING:
    import polars as pl

    from stock_analytics.metrics.context import MetricContext


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


def run_market_temperature(
    *,
    target_date: date | None = None,
    comparison_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
    collect_metric_values: bool | None = None,
    storage_dir: Path | str | None = None,
    market_daily: pl.DataFrame | None = None,
    dataset_cache: DatasetFrameCache | None = None,
    trade_dates: tuple[date, ...] | None = None,
    metric_contexts: dict[int, MetricContext] | None = None,
) -> MarketTemperatureRunResult:
    """运行市场温度计事实采集、评分结构生成与产物写入。"""
    config = load_market_temperature_config(config_path).with_artifact_root(output_root)
    if trade_dates is None:
        as_of_date, resolved_trade_dates = resolve_trade_window(
            config,
            target_date,
            storage_dir=storage_dir,
        )
    else:
        resolved_trade_dates = tuple(
            sorted(value for value in trade_dates if target_date is None or value <= target_date)
        )[-max(config.main_window, *config.short_windows) :]
        if not resolved_trade_dates:
            raise ValueError("传入的市场温度交易日窗口为空")
        as_of_date = target_date or resolved_trade_dates[-1]
    paths = build_run_paths(as_of_date, config.artifact_root)
    external_cutoff_date = resolve_external_cutoff_date(as_of_date, resolved_trade_dates)
    comparison = _load_comparison(config.artifact_root, comparison_date)
    manifest = _build_manifest(
        config,
        as_of_date,
        resolved_trade_dates,
        paths,
        external_cutoff_date=external_cutoff_date,
        comparison=comparison,
    )
    facts = collect_facts(
        config,
        as_of_date=as_of_date,
        trade_dates=resolved_trade_dates,
        storage_dir=storage_dir,
        collect_metric_values=collect_metric_values,
        market_daily=market_daily,
        dataset_cache=dataset_cache,
        metric_contexts=metric_contexts,
        external_cutoff_date=external_cutoff_date,
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
    from stock_reporting.core.quality import render_quality_report_markdown
    from stock_reporting.templates.market_temperature import (
        build_report_json,
        render_human_report_markdown,
        render_report_markdown,
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
        comparison=comparison,
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
    *,
    external_cutoff_date: date | None,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = paths.run_dir.name
    manifest = {
        "schema_version": config.schema_version,
        "title": config.title,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "main_window": config.main_window,
        "short_windows": list(config.short_windows),
        "trade_dates": [value.isoformat() for value in trade_dates],
        "source_cutoffs": {
            "external_market": (
                external_cutoff_date.isoformat() if external_cutoff_date is not None else None
            )
        },
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
    if comparison:
        previous_manifest = comparison.get("previous_manifest", {})
        if isinstance(previous_manifest, dict):
            manifest["comparison"] = {
                "previous_as_of_date": previous_manifest.get("as_of_date"),
                "previous_run_id": previous_manifest.get("run_id"),
            }
    return manifest


def _load_comparison(
    artifact_root: Path | str,
    comparison_date: date | None,
) -> dict[str, Any] | None:
    if comparison_date is None:
        return None
    run_root = Path(artifact_root) / "runs" / f"as_of={comparison_date.isoformat()}"
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"未找到对比日期的市场温度计产物: {comparison_date.isoformat()}")
    previous_run = run_dirs[-1]
    return {
        "previous_manifest": _read_json(previous_run / "manifest.json"),
        "previous_scores": _read_json(previous_run / "scores.json"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少对比产物文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"对比产物不是 JSON 对象: {path}")
    return payload
