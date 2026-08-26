"""投资者简报产物管线编排。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.artifact_reader import resolve_artifact_run
from stock_analytics.pipelines.investor_brief.artifacts import (
    InvestorBriefArtifactPayload,
    InvestorBriefRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.manifest import build_manifest_base
from stock_reporting.interpretation.investor_brief.config import (
    DEFAULT_CONFIG_PATH,
    InvestorBriefConfig,
    load_investor_brief_config,
)


@dataclass(frozen=True, slots=True)
class InvestorBriefRunResult:
    """投资者简报一次运行结果。"""

    as_of_date: date
    paths: InvestorBriefRunPaths
    manifest: dict[str, Any]
    brief_markdown: str
    brief_json: dict[str, Any]


def run_investor_brief(
    *,
    target_date: date | None = None,
    market_run_id: str | None = None,
    industry_run_id: str | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    market_temperature_root: Path | str | None = None,
    industry_structure_root: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
) -> InvestorBriefRunResult:
    """读取市场温度和行业结构产物，生成普通投资者简报。"""
    _validate_upstream_selection(target_date, market_run_id, industry_run_id)
    config = load_investor_brief_config(config_path).with_artifact_root(output_root)
    if market_temperature_root is not None:
        config = replace(config, market_temperature_root=Path(market_temperature_root))
    if industry_structure_root is not None:
        config = replace(config, industry_structure_root=Path(industry_structure_root))
    resolved_date = (
        target_date
        if target_date is not None
        else _resolve_latest_common_date(
            config.market_temperature_root,
            config.industry_structure_root,
        )
    )
    market = _load_market_artifacts(config, resolved_date, run_id=market_run_id)
    industry = _load_industry_artifacts(config, resolved_date, run_id=industry_run_id)
    as_of_date = _resolve_as_of_date(market["manifest"], industry["manifest"])
    paths = build_run_paths(as_of_date, config.artifact_root, run_class=run_class)
    manifest = _build_manifest(
        config,
        as_of_date,
        paths,
        market=market,
        industry=industry,
        config_path=config_path,
    )

    from stock_reporting.templates.investor_brief import build_brief_json, render_brief_markdown

    brief_json = build_brief_json(
        config=config,
        manifest=manifest,
        market_scores=market["scores"],
        industry_scores=industry["scores"],
        industry_panel=industry["industry_panel"],
        market_facts=market["facts"],
    )
    brief_markdown = render_brief_markdown(brief_json)
    write_artifacts(
        paths,
        InvestorBriefArtifactPayload(
            manifest=manifest,
            brief_markdown=brief_markdown,
            brief_json=brief_json,
        ),
        update_latest=update_latest,
    )
    return InvestorBriefRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        brief_markdown=brief_markdown,
        brief_json=brief_json,
    )


def _load_market_artifacts(
    config: InvestorBriefConfig,
    target_date: date,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    run = resolve_artifact_run(
        config.market_temperature_root,
        as_of_date=target_date,
        expected_artifact_type="market_temperature",
        run_id=run_id,
    )
    facts_path = run.path("facts.parquet")
    return {
        "artifact_dir": run.run_dir,
        "manifest": run.manifest,
        "scores": run.read_json("scores.json"),
        "facts": pl.read_parquet(facts_path) if facts_path.exists() else pl.DataFrame(),
    }


def _load_industry_artifacts(
    config: InvestorBriefConfig,
    target_date: date,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    run = resolve_artifact_run(
        config.industry_structure_root,
        as_of_date=target_date,
        expected_artifact_type="industry_structure",
        run_id=run_id,
    )
    return {
        "artifact_dir": run.run_dir,
        "manifest": run.manifest,
        "scores": run.read_json("scores.json"),
        "industry_panel": pl.read_parquet(run.path("industry_panel.parquet")),
    }


def _resolve_latest_common_date(market_root: Path, industry_root: Path) -> date:
    """返回两个上游产物共同拥有的最新观测日期。"""
    market_dates = _available_run_dates(market_root)
    industry_dates = _available_run_dates(industry_root)
    common_dates = market_dates & industry_dates
    if not common_dates:
        raise FileNotFoundError(
            "市场温度和行业结构没有共同的已落盘观测日期，请先生成同一 DATE 的上游产物"
        )
    return max(common_dates)


def _available_run_dates(root: Path) -> set[date]:
    """扫描包含运行目录的 as_of 分区。"""
    run_root = root / "runs"
    if not run_root.exists():
        return set()
    dates: set[date] = set()
    for path in run_root.glob("as_of=*"):
        if not path.is_dir() or not any(child.is_dir() for child in path.glob("run_*")):
            continue
        try:
            dates.add(date.fromisoformat(path.name.removeprefix("as_of=")))
        except ValueError:
            continue
    return dates


def _validate_upstream_selection(
    target_date: date | None,
    market_run_id: str | None,
    industry_run_id: str | None,
) -> None:
    if (market_run_id is None) != (industry_run_id is None):
        raise ValueError("market_run_id 和 industry_run_id 必须同时提供")
    if target_date is None and market_run_id is not None:
        raise ValueError("指定上游 run_id 时必须同时提供 target_date")


def _resolve_as_of_date(
    market_manifest: dict[str, Any],
    industry_manifest: dict[str, Any],
) -> date:
    market_date = str(market_manifest.get("as_of_date") or "")
    industry_date = str(industry_manifest.get("as_of_date") or "")
    if not market_date or not industry_date:
        raise ValueError("上游产物缺少 as_of_date")
    if market_date != industry_date:
        raise ValueError(f"上游产物基准日不一致: market={market_date}, industry={industry_date}")
    return date.fromisoformat(market_date)


def _build_manifest(
    config: InvestorBriefConfig,
    as_of_date: date,
    paths: InvestorBriefRunPaths,
    *,
    market: dict[str, Any],
    industry: dict[str, Any],
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    inputs = {
        "market_temperature": _input_manifest(market),
        "industry_structure": _input_manifest(industry),
    }
    parents = {
        name: {
            "as_of_date": value.get("as_of_date"),
            "run_id": value.get("run_id"),
            "run_class": value.get("run_class", "official"),
        }
        for name, value in inputs.items()
    }
    manifest = build_manifest_base(
        artifact_type="investor_brief",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=paths.root,
        config_path=config_path,
        inputs=inputs,
        parents=parents,
    )
    manifest["files"] = {
        "manifest": paths.manifest.name,
        "brief_report_md": paths.brief_md.name,
        "brief_report_json": paths.brief_json.name,
    }
    return manifest


def _input_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload["manifest"]
    artifact_dir = payload["artifact_dir"]
    return {
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "run_class": manifest.get("run_class", "official"),
        "artifact_dir": str(artifact_dir),
    }
