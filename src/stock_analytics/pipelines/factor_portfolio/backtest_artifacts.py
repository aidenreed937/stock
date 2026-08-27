"""因子组合分数面板读取与策略层回测产物写入。

回测产物（``artifact_type="factor_backtest"``）由 ``stock_strategy`` 侧生成，
本模块提供其文件生命周期（路径构造 + 事务写入），供策略层经 2-dot 包门面消费，
避免外部消费者直连 analytics 实现模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactRunPaths,
    ArtifactStore,
    RunClass,
    build_manifest_base,
    resolve_artifact_run,
)

MappingLike = dict[str, Any]

_SCORES_FILENAME = "factor_portfolio_scores.csv"
_DEFAULT_PORTFOLIO_ROOT = "data/analytics/factor_portfolio"


@dataclass(frozen=True, slots=True)
class BacktestRunPaths:
    """一次因子组合回测运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    report_md: Path
    report_json: Path
    nav_csv: Path
    run_class: RunClass = "official"


@dataclass(frozen=True, slots=True)
class BacktestArtifactPayload:
    """一次回测运行需要写入的产物内容。"""

    manifest: MappingLike
    report_markdown: str
    report_json: MappingLike
    nav: pl.DataFrame


def load_latest_scores(
    portfolio_root: Path | str = _DEFAULT_PORTFOLIO_ROOT,
) -> tuple[Path, pl.DataFrame, MappingLike]:
    """读取 factor_portfolio latest 组合分数面板与组合说明（回测输入）。

    Returns:
        (run_dir, scores, summary): 分数面板（trade_date / symbol / composite_score）
        与组合说明（因子清单、窗口、参数、来源报告）。

    Raises:
        ArtifactUnavailableError: latest 产物缺失或校验失败。
    """
    run = resolve_artifact_run(
        portfolio_root,
        expected_artifact_type="factor_portfolio",
    )
    scores = pl.read_csv(run.path(_SCORES_FILENAME), try_parse_dates=True)
    summary = run.read_json("factor_portfolio.json")
    return run.run_dir, scores, summary


def build_backtest_manifest(
    *,
    title: str,
    run_id: str,
    as_of_date: date,
    artifact_root: Path | str,
    config_path: Path | str | None,
    inputs: MappingLike,
    parents: MappingLike,
) -> MappingLike:
    """构造回测产物 Manifest（schema_version=1）。"""
    return build_manifest_base(
        artifact_type="factor_backtest",
        schema_version=1,
        title=title,
        run_id=run_id,
        as_of_date=as_of_date,
        artifact_root=artifact_root,
        config_path=config_path,
        inputs=inputs,
        parents=parents,
    )


def build_backtest_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    latest_root: Path | str | None = None,
    run_class: RunClass = "official",
) -> BacktestRunPaths:
    """按基准日与 run_id 构造回测运行和共享 latest 产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        latest_root=latest_root,
        run_class=run_class,
    )
    return BacktestRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        report_md=generic.run_dir / "factor_backtest.md",
        report_json=generic.run_dir / "factor_backtest.json",
        nav_csv=generic.run_dir / "factor_backtest_nav.csv",
    )


def write_backtest_artifacts(
    paths: BacktestRunPaths,
    payload: BacktestArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次回测运行的 manifest、报告与净值序列产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="factor_backtest",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_text("factor_backtest.md", payload.report_markdown)
        session.write_json("factor_backtest.json", payload.report_json)
        session.write_csv("factor_backtest_nav.csv", payload.nav)


__all__ = [
    "BacktestArtifactPayload",
    "BacktestRunPaths",
    "build_backtest_manifest",
    "build_backtest_run_paths",
    "load_latest_scores",
    "write_backtest_artifacts",
]
