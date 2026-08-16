"""投资者简报产物管线编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import polars as pl

from stock.analytics.investor_brief.artifacts import (
    InvestorBriefArtifactPayload,
    InvestorBriefRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock.analytics.investor_brief.config import (
    DEFAULT_CONFIG_PATH,
    InvestorBriefConfig,
    load_investor_brief_config,
)
from stock.analytics.investor_brief.templates import build_brief_json, render_brief_markdown

if TYPE_CHECKING:
    from pathlib import Path


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
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    update_latest: bool = True,
) -> InvestorBriefRunResult:
    """读取市场温度和行业结构产物，生成普通投资者简报。"""
    config = load_investor_brief_config(config_path).with_artifact_root(output_root)
    market = _load_market_artifacts(config, target_date)
    industry = _load_industry_artifacts(config, target_date)
    as_of_date = _resolve_as_of_date(market["manifest"], industry["manifest"])
    paths = build_run_paths(as_of_date, config.artifact_root)
    manifest = _build_manifest(config, as_of_date, paths, market=market, industry=industry)
    brief_json = build_brief_json(
        config=config,
        manifest=manifest,
        market_scores=market["scores"],
        industry_scores=industry["scores"],
        industry_panel=industry["industry_panel"],
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
    target_date: date | None,
) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.market_temperature_root, target_date)
    return {
        "artifact_dir": artifact_dir,
        "manifest": _read_json(artifact_dir / "manifest.json"),
        "scores": _read_json(artifact_dir / "scores.json"),
    }


def _load_industry_artifacts(
    config: InvestorBriefConfig,
    target_date: date | None,
) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.industry_structure_root, target_date)
    return {
        "artifact_dir": artifact_dir,
        "manifest": _read_json(artifact_dir / "manifest.json"),
        "scores": _read_json(artifact_dir / "scores.json"),
        "industry_panel": pl.read_parquet(artifact_dir / "industry_panel.parquet"),
    }


def _resolve_artifact_dir(root: Path, target_date: date | None) -> Path:
    if target_date is None:
        latest = root / "latest"
        if not latest.exists():
            raise FileNotFoundError(f"未找到 latest 产物目录: {latest}")
        return latest
    run_root = root / "runs" / f"as_of={target_date.isoformat()}"
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"未找到基准日 {target_date.isoformat()} 的产物目录: {run_root}")
    return run_dirs[-1]


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
    artifact_dir = payload["artifact_dir"]
    return {
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "artifact_dir": str(artifact_dir),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少产物文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"产物不是 JSON 对象: {path}")
    return payload
