"""个股排雷运行产物写入。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(frozen=True, slots=True)
class StockScreenRunPaths:
    """一次排雷运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    excluded: Path
    warned: Path
    passed: Path
    scored: Path
    scores: Path
    report_md: Path
    report_json: Path
    quality_report_md: Path
    quality_report_json: Path


@dataclass(frozen=True, slots=True)
class StockScreenArtifactPayload:
    """一次排雷运行需要写入的内容。"""

    manifest: dict[str, Any]
    excluded: pl.DataFrame
    warned: pl.DataFrame
    passed: pl.DataFrame
    scored: pl.DataFrame
    scores: dict[str, Any]
    report_markdown: str
    report_json: dict[str, Any]
    quality_report_markdown: str
    quality_report_json: dict[str, Any]


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
) -> StockScreenRunPaths:
    """按基准日与运行 ID 构造产物路径。"""
    root = Path(artifact_root)
    actual_run_id = run_id or f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
    latest_dir = root / "latest"
    return StockScreenRunPaths(
        root=root,
        run_dir=run_dir,
        latest_dir=latest_dir,
        manifest=run_dir / "manifest.json",
        excluded=run_dir / "excluded.csv",
        warned=run_dir / "warned.csv",
        passed=run_dir / "passed.csv",
        scored=run_dir / "scored.parquet",
        scores=run_dir / "scores.json",
        report_md=run_dir / "screen_report.md",
        report_json=run_dir / "screen_report.json",
        quality_report_md=run_dir / "quality_report.md",
        quality_report_json=run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: StockScreenRunPaths,
    payload: StockScreenArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入排雷清单、摘要和质量报告。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(paths.manifest, payload.manifest)
    _csv_frame(payload.excluded).write_csv(paths.excluded)
    _csv_frame(payload.warned).write_csv(paths.warned)
    _csv_frame(payload.passed).write_csv(paths.passed)
    if not payload.scored.is_empty():
        payload.scored.write_parquet(paths.scored)
    _write_json(paths.scores, payload.scores)
    paths.report_md.write_text(payload.report_markdown, encoding="utf-8")
    _write_json(paths.report_json, payload.report_json)
    paths.quality_report_md.write_text(payload.quality_report_markdown, encoding="utf-8")
    _write_json(paths.quality_report_json, payload.quality_report_json)
    if update_latest:
        _copy_to_latest(paths)


def _copy_to_latest(paths: StockScreenRunPaths) -> None:
    paths.latest_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        paths.manifest,
        paths.excluded,
        paths.warned,
        paths.passed,
        paths.scored,
        paths.scores,
        paths.report_md,
        paths.report_json,
        paths.quality_report_md,
        paths.quality_report_json,
    ):
        if source.exists():
            shutil.copy2(source, paths.latest_dir / source.name)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _csv_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """将输出契约中的列表列转换为 CSV 可写的文本列。"""
    expressions = []
    if "reasons" in frame.columns:
        expressions.append(pl.col("reasons").list.join("；").alias("reasons"))
    for column in ("rule_ids", "missing_rules"):
        if column in frame.columns:
            expressions.append(pl.col(column).list.join(",").alias(column))
    return frame.with_columns(expressions) if expressions else frame


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


__all__ = [
    "StockScreenArtifactPayload",
    "StockScreenRunPaths",
    "build_run_paths",
    "write_artifacts",
]
