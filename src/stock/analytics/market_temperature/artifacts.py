"""市场温度计运行产物写入。"""

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
class MarketTemperatureRunPaths:
    """一次市场温度计运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    facts: Path
    scores: Path
    report_md: Path
    report_json: Path
    human_report_md: Path


@dataclass(frozen=True, slots=True)
class MarketTemperatureArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    facts: pl.DataFrame
    scores: MappingLike
    report_markdown: str
    report_json: MappingLike
    human_report_markdown: str


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
) -> MarketTemperatureRunPaths:
    """按 as_of 日期与 run_id 构造产物路径。"""
    root = Path(artifact_root)
    actual_run_id = run_id or f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
    latest_dir = root / "latest"
    return MarketTemperatureRunPaths(
        root=root,
        run_dir=run_dir,
        latest_dir=latest_dir,
        manifest=run_dir / "manifest.json",
        facts=run_dir / "facts.parquet",
        scores=run_dir / "scores.json",
        report_md=run_dir / "report.md",
        report_json=run_dir / "report.json",
        human_report_md=run_dir / "human_report.md",
    )


def write_artifacts(
    paths: MarketTemperatureRunPaths,
    payload: MarketTemperatureArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest、facts、scores 和报告产物。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(paths.manifest, payload.manifest)
    payload.facts.write_parquet(paths.facts)
    _write_json(paths.scores, payload.scores)
    paths.report_md.write_text(payload.report_markdown, encoding="utf-8")
    _write_json(paths.report_json, payload.report_json)
    paths.human_report_md.write_text(payload.human_report_markdown, encoding="utf-8")

    if update_latest:
        _copy_to_latest(paths)


def _copy_to_latest(paths: MarketTemperatureRunPaths) -> None:
    paths.latest_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        paths.manifest,
        paths.facts,
        paths.scores,
        paths.report_md,
        paths.report_json,
        paths.human_report_md,
    ):
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
