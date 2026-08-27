"""因子组合分数产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class FactorPortfolioRunPaths:
    """一次因子组合分数运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    scores_csv: Path
    summary_json: Path
    run_class: RunClass = "official"


@dataclass(frozen=True, slots=True)
class FactorPortfolioArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    scores: pl.DataFrame
    summary: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    latest_root: Path | str | None = None,
    run_class: RunClass = "official",
) -> FactorPortfolioRunPaths:
    """按基准日与 run_id 构造运行和共享 latest 产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        latest_root=latest_root,
        run_class=run_class,
    )
    return FactorPortfolioRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        scores_csv=generic.run_dir / "factor_portfolio_scores.csv",
        summary_json=generic.run_dir / "factor_portfolio.json",
    )


def write_artifacts(
    paths: FactorPortfolioRunPaths,
    payload: FactorPortfolioArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest、组合分数面板与组合说明产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="factor_portfolio",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_csv("factor_portfolio_scores.csv", payload.scores)
        session.write_json("factor_portfolio.json", payload.summary)


__all__ = [
    "FactorPortfolioArtifactPayload",
    "FactorPortfolioRunPaths",
    "build_run_paths",
    "write_artifacts",
]
