"""全市场聚合监控运行产物写入。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class MarketAggregateRunPaths:
    """一次全市场聚合运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    snapshot: Path
    facts: Path
    trend: Path
    industry_breadth: Path
    report_md: Path
    report_json: Path
    human_report_md: Path
    quality_report_md: Path
    quality_report_json: Path


@dataclass(frozen=True, slots=True)
class MarketAggregateArtifactPayload:
    """一次聚合运行需要写入的产物内容。"""

    manifest: MappingLike
    snapshot: MappingLike
    facts: pl.DataFrame
    trend: pl.DataFrame
    industry_breadth: pl.DataFrame | None = None
    report_markdown: str = ""
    report_json: MappingLike | None = None
    human_report_markdown: str = ""
    quality_report_markdown: str = ""
    quality_report_json: MappingLike | None = None


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
) -> MarketAggregateRunPaths:
    """按行情日期和运行 ID 构造产物路径。"""
    root = Path(artifact_root)
    actual_run_id = run_id or f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
    latest_dir = root / "latest"
    return MarketAggregateRunPaths(
        root=root,
        run_dir=run_dir,
        latest_dir=latest_dir,
        manifest=run_dir / "manifest.json",
        snapshot=run_dir / "snapshot.json",
        facts=run_dir / "facts.parquet",
        trend=run_dir / "trend.parquet",
        industry_breadth=run_dir / "industry_breadth.parquet",
        report_md=run_dir / "report.md",
        report_json=run_dir / "report.json",
        human_report_md=run_dir / "human_report.md",
        quality_report_md=run_dir / "quality_report.md",
        quality_report_json=run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: MarketAggregateRunPaths,
    payload: MarketAggregateArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入聚合快照、事实表、报告和质量产物。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(paths.manifest, payload.manifest)
    _write_json(paths.snapshot, payload.snapshot)
    payload.facts.write_parquet(paths.facts)
    payload.trend.write_parquet(paths.trend)
    if payload.industry_breadth is not None:
        payload.industry_breadth.write_parquet(paths.industry_breadth)
    paths.report_md.write_text(payload.report_markdown, encoding="utf-8")
    _write_json(paths.report_json, _require_mapping(payload.report_json, "report_json"))
    paths.human_report_md.write_text(payload.human_report_markdown, encoding="utf-8")
    paths.quality_report_md.write_text(payload.quality_report_markdown, encoding="utf-8")
    _write_json(
        paths.quality_report_json,
        _require_mapping(payload.quality_report_json, "quality_report_json"),
    )

    if update_latest:
        _copy_to_latest(paths)


def _require_mapping(value: MappingLike | None, name: str) -> MappingLike:
    if value is None:
        raise ValueError(f"产物 {name} 缺失，无法写入")
    return value


def _copy_to_latest(paths: MarketAggregateRunPaths) -> None:
    paths.latest_dir.mkdir(parents=True, exist_ok=True)
    sources = [
        paths.manifest,
        paths.snapshot,
        paths.facts,
        paths.trend,
        paths.report_md,
        paths.report_json,
        paths.human_report_md,
        paths.quality_report_md,
        paths.quality_report_json,
    ]
    if paths.industry_breadth.exists():
        sources.append(paths.industry_breadth)
    for source in sources:
        shutil.copy2(source, paths.latest_dir / source.name)


def _write_json(path: Path, payload: MappingLike) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


__all__ = [
    "MarketAggregateArtifactPayload",
    "MarketAggregateRunPaths",
    "build_run_paths",
    "write_artifacts",
]
