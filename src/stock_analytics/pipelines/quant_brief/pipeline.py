"""量化投研简报产物管线编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.quant_brief.artifacts import (
    QuantBriefArtifactPayload,
    QuantBriefRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_reporting.interpretation.quant_brief.config import (
    DEFAULT_CONFIG_PATH,
    QuantBriefConfig,
    load_quant_brief_config,
)


@dataclass(frozen=True, slots=True)
class QuantBriefRunResult:
    """量化投研简报一次运行结果。"""

    as_of_date: date
    paths: QuantBriefRunPaths
    manifest: dict[str, Any]
    brief_markdown: str
    brief_json: dict[str, Any]


def run_quant_brief(
    *,
    target_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
) -> QuantBriefRunResult:
    """读取市场温度和行业结构产物，生成量化投研简报。"""
    config = load_quant_brief_config(config_path).with_artifact_root(output_root)
    resolved_date = target_date or _resolve_latest_common_date(
        config.market_temperature_root,
        config.industry_structure_root,
    )
    market = _load_market_artifacts(config, resolved_date)
    industry = _load_industry_artifacts(config, resolved_date)
    as_of_date = _resolve_as_of_date(market["manifest"], industry["manifest"])
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = _build_manifest(config, as_of_date, paths, market=market, industry=industry)

    from stock_reporting.templates.quant_brief import (
        build_quant_brief_json,
        render_quant_brief_markdown,
    )

    brief_json = build_quant_brief_json(
        config=config,
        manifest=manifest,
        market_scores=market["scores"],
        industry_scores=industry["scores"],
        industry_panel=industry["industry_panel"],
        market_facts=market["facts"],
    )
    brief_markdown = render_quant_brief_markdown(brief_json)
    write_artifacts(
        paths,
        QuantBriefArtifactPayload(
            manifest=manifest,
            brief_markdown=brief_markdown,
            brief_json=brief_json,
        ),
        update_latest=update_latest,
    )
    return QuantBriefRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        brief_markdown=brief_markdown,
        brief_json=brief_json,
    )


def _load_market_artifacts(config: QuantBriefConfig, target_date: date) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.market_temperature_root, target_date)
    facts_path = artifact_dir / "facts.parquet"
    return {
        "artifact_dir": artifact_dir,
        "manifest": _read_json(artifact_dir / "manifest.json"),
        "scores": _read_json(artifact_dir / "scores.json"),
        "facts": pl.read_parquet(facts_path) if facts_path.exists() else pl.DataFrame(),
    }


def _load_industry_artifacts(config: QuantBriefConfig, target_date: date) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.industry_structure_root, target_date)
    return {
        "artifact_dir": artifact_dir,
        "manifest": _read_json(artifact_dir / "manifest.json"),
        "scores": _read_json(artifact_dir / "scores.json"),
        "industry_panel": pl.read_parquet(artifact_dir / "industry_panel.parquet"),
    }


def _resolve_latest_common_date(market_root: Path, industry_root: Path) -> date:
    """返回两个上游产物共同拥有的最新观测日期。"""
    common_dates = _available_run_dates(market_root) & _available_run_dates(industry_root)
    if not common_dates:
        raise FileNotFoundError(
            "市场温度和行业结构没有共同的已落盘观测日期，请先生成同一 DATE 的上游产物"
        )
    return max(common_dates)


def _available_run_dates(root: Path) -> set[date]:
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


def _resolve_artifact_dir(root: Path, target_date: date) -> Path:
    run_root = root / "runs" / f"as_of={target_date.isoformat()}"
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"未找到基准日 {target_date.isoformat()} 的产物目录: {run_root}")
    return run_dirs[-1]


def _resolve_as_of_date(market_manifest: dict[str, Any], industry_manifest: dict[str, Any]) -> date:
    market_date = str(market_manifest.get("as_of_date") or "")
    industry_date = str(industry_manifest.get("as_of_date") or "")
    if not market_date or not industry_date:
        raise ValueError("上游产物缺少 as_of_date")
    if market_date != industry_date:
        raise ValueError(f"上游产物基准日不一致: market={market_date}, industry={industry_date}")
    return date.fromisoformat(market_date)


def _build_manifest(
    config: QuantBriefConfig,
    as_of_date: date,
    paths: QuantBriefRunPaths,
    *,
    market: dict[str, Any],
    industry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "run_id": paths.run_dir.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "artifact_root": str(paths.root),
        "inputs": {
            "market_temperature": _input_manifest(market),
            "industry_structure": _input_manifest(industry),
        },
        "files": {
            "manifest": paths.manifest.name,
            "brief_report_md": paths.brief_md.name,
            "brief_report_json": paths.brief_json.name,
        },
    }


def _input_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload["manifest"]
    return {
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "artifact_dir": str(payload["artifact_dir"]),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少产物文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"产物不是 JSON 对象: {path}")
    return payload


__all__ = ["QuantBriefRunResult", "run_quant_brief"]
