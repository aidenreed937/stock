"""市场温度计运行产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore
from stock_analytics.pipelines.market_temperature.history import update_history_index

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
    snapshot: Path
    report_md: Path
    report_json: Path
    human_report_md: Path
    quality_report_md: Path
    quality_report_json: Path
    run_class: RunClass = "official"


@dataclass(frozen=True, slots=True)
class MarketTemperatureArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    facts: pl.DataFrame
    scores: MappingLike
    snapshot: MappingLike
    report_markdown: str
    report_json: MappingLike
    human_report_markdown: str
    quality_report_markdown: str
    quality_report_json: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    run_class: RunClass = "official",
) -> MarketTemperatureRunPaths:
    """按 as_of 日期与 run_id 构造产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        run_class=run_class,
    )
    return MarketTemperatureRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        facts=generic.run_dir / "facts.parquet",
        scores=generic.run_dir / "scores.json",
        snapshot=generic.run_dir / "snapshot.json",
        report_md=generic.run_dir / "report.md",
        report_json=generic.run_dir / "report.json",
        human_report_md=generic.run_dir / "human_report.md",
        quality_report_md=generic.run_dir / "quality_report.md",
        quality_report_json=generic.run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: MarketTemperatureRunPaths,
    payload: MarketTemperatureArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest、facts、scores 和报告产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="market_temperature",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_parquet("facts.parquet", payload.facts)
        session.write_json("scores.json", payload.scores)
        session.write_json("snapshot.json", payload.snapshot)
        session.write_text("report.md", payload.report_markdown)
        session.write_json("report.json", payload.report_json)
        session.write_text("human_report.md", payload.human_report_markdown)
        session.write_text("quality_report.md", payload.quality_report_markdown)
        session.write_json("quality_report.json", payload.quality_report_json)
    update_history_index(
        paths.root,
        manifest=payload.manifest,
        snapshot=payload.snapshot,
    )
