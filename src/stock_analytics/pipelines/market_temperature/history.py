"""市场温度跨运行历史索引。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.market_temperature.snapshot import build_market_state_snapshot

HISTORY_INDEX_NAME = "history.parquet"
_HISTORY_SCHEMA = {
    "as_of_date": pl.Date,
    "run_id": pl.String,
    "run_class": pl.String,
    "composite_temperature": pl.Float64,
    "temperature_status": pl.String,
    "risk_level": pl.String,
    "risk_status": pl.String,
    "red_flag_count": pl.Int64,
    "warning_count": pl.Int64,
    "offset_count": pl.Int64,
    "dimensions_json": pl.String,
    "config_hash": pl.String,
    "data_fingerprint": pl.String,
    "code_version": pl.String,
    "schema_version": pl.Int64,
    "generated_at": pl.String,
    "is_latest_for_date": pl.Boolean,
}


def history_index_path(artifact_root: Path | str) -> Path:
    """返回市场温度历史索引路径。"""
    return Path(artifact_root) / "index" / HISTORY_INDEX_NAME


def update_history_index(
    artifact_root: Path | str,
    *,
    manifest: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Path:
    """幂等写入当前运行，并原子替换历史索引。"""
    path = history_index_path(artifact_root)
    rows = _read_rows(path)
    current = _history_row(manifest, snapshot)
    rows = [row for row in rows if row.get("run_id") != current["run_id"]]
    rows.append(current)
    frame = _frame_from_rows(_mark_latest(rows))
    _write_atomic(path, frame)
    return path


def rebuild_history_index(artifact_root: Path | str) -> Path:
    """从已有运行快照重建历史索引。"""
    root = Path(artifact_root)
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in root.glob("runs/as_of=*/run_*") if path.is_dir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _read_json(manifest_path)
        snapshot_path = run_dir / "snapshot.json"
        snapshot = (
            _read_json(snapshot_path)
            if snapshot_path.exists()
            else build_market_state_snapshot(
                manifest=manifest, scores=_read_json(run_dir / "scores.json"), config_path=None
            )
        )
        rows.append(_history_row(manifest, snapshot))
    path = history_index_path(root)
    _write_atomic(path, _frame_from_rows(_mark_latest(rows)))
    return path


def load_history_index(artifact_root: Path | str) -> pl.DataFrame | None:
    """读取历史索引；索引不存在时返回 None。"""
    path = history_index_path(artifact_root)
    if not path.exists():
        return None
    return pl.read_parquet(path)


def _history_row(manifest: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    identity = _mapping(snapshot.get("identity"))
    composite = _mapping(snapshot.get("composite"))
    risk = _mapping(snapshot.get("systemic_risk"))
    dimensions = snapshot.get("dimensions", [])
    as_of_value = str(manifest.get("as_of_date") or snapshot.get("as_of_date") or "")
    return {
        "as_of_date": date.fromisoformat(as_of_value),
        "run_id": str(manifest.get("run_id") or snapshot.get("run_id") or ""),
        "run_class": str(manifest.get("run_class") or "official"),
        "composite_temperature": _as_float(composite.get("temperature")),
        "temperature_status": str(composite.get("status") or "pending"),
        "risk_level": str(risk.get("level") or "不可判定"),
        "risk_status": str(risk.get("status") or "pending"),
        "red_flag_count": _list_length(risk.get("red_flags")),
        "warning_count": _list_length(risk.get("warnings")),
        "offset_count": _list_length(risk.get("offsets")),
        "dimensions_json": json.dumps(dimensions, ensure_ascii=False, sort_keys=True, default=str),
        "config_hash": str(identity.get("config_hash") or ""),
        "data_fingerprint": str(identity.get("data_fingerprint") or ""),
        "code_version": str(identity.get("code_version") or ""),
        "schema_version": int(snapshot.get("schema_version") or 1),
        "generated_at": str(manifest.get("generated_at") or ""),
        "is_latest_for_date": False,
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pl.read_parquet(path).to_dicts()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 产物必须是对象: {path}")
    return value


def _mark_latest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_date: dict[date, dict[str, Any]] = {}
    for row in rows:
        row["as_of_date"] = _as_date(row.get("as_of_date"))
        current = latest_by_date.get(row["as_of_date"])
        if current is None or _row_order(row) > _row_order(current):
            latest_by_date[row["as_of_date"]] = row
    for row in rows:
        row["is_latest_for_date"] = latest_by_date[row["as_of_date"]] is row
    return rows


def _row_order(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("generated_at") or ""), str(row.get("run_id") or "")


def _frame_from_rows(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=_HISTORY_SCHEMA)
    return pl.DataFrame(rows, schema=_HISTORY_SCHEMA, strict=False).sort(
        ["as_of_date", "generated_at", "run_id"]
    )


def _write_atomic(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        frame.write_parquet(temporary_path)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _list_length(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


__all__ = [
    "HISTORY_INDEX_NAME",
    "history_index_path",
    "load_history_index",
    "rebuild_history_index",
    "update_history_index",
]
