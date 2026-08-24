"""全市场聚合监控运行产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore

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
    run_class: RunClass = "official"


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
    *,
    run_class: RunClass = "official",
) -> MarketAggregateRunPaths:
    """按行情日期和运行 ID 构造产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        run_class=run_class,
    )
    return MarketAggregateRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        snapshot=generic.run_dir / "snapshot.json",
        facts=generic.run_dir / "facts.parquet",
        trend=generic.run_dir / "trend.parquet",
        industry_breadth=generic.run_dir / "industry_breadth.parquet",
        report_md=generic.run_dir / "report.md",
        report_json=generic.run_dir / "report.json",
        human_report_md=generic.run_dir / "human_report.md",
        quality_report_md=generic.run_dir / "quality_report.md",
        quality_report_json=generic.run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: MarketAggregateRunPaths,
    payload: MarketAggregateArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入聚合快照、事实表、报告和质量产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="market_aggregate",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_json("snapshot.json", payload.snapshot)
        session.write_parquet("facts.parquet", payload.facts)
        session.write_parquet("trend.parquet", payload.trend)
        if payload.industry_breadth is not None:
            session.write_parquet("industry_breadth.parquet", payload.industry_breadth)
        session.write_text("report.md", payload.report_markdown)
        session.write_json("report.json", _require_mapping(payload.report_json, "report_json"))
        session.write_text("human_report.md", payload.human_report_markdown)
        session.write_text("quality_report.md", payload.quality_report_markdown)
        session.write_json(
            "quality_report.json",
            _require_mapping(payload.quality_report_json, "quality_report_json"),
        )


def _require_mapping(value: MappingLike | None, name: str) -> MappingLike:
    if value is None:
        raise ValueError(f"产物 {name} 缺失，无法写入")
    return value


__all__ = [
    "MarketAggregateArtifactPayload",
    "MarketAggregateRunPaths",
    "build_run_paths",
    "write_artifacts",
]
