"""Tariffline RAW 快照路径、文件与 manifest 存储。"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.customs.collectors.tariffline_types import TarifflineStatus


def query_digest(cmd_codes: list[str]) -> str:
    return hashlib.sha256(",".join(cmd_codes).encode()).hexdigest()[:12]


def snapshot_path(
    raw_dir: Path | str,
    periods: list[str],
    flow_code: str,
    cmd_codes: list[str],
) -> Path:
    period_key = f"{periods[0]}-{periods[-1]}"
    flow_key = flow_code.replace(",", "_")
    request_digest = hashlib.sha256(
        f"{','.join(periods)}|{flow_code}|{','.join(cmd_codes)}".encode()
    ).hexdigest()[:12]
    return (
        Path(raw_dir)
        / f"period={period_key}"
        / f"flow={flow_key}"
        / f"batch={request_digest}"
        / "data.parquet"
    )


def legacy_snapshot_path(
    raw_dir: Path | str,
    periods: list[str],
    flow_code: str,
    cmd_codes: list[str],
    output_name: str | None = None,
) -> Path:
    stem = output_name or "_".join(periods)
    suffix = f"_tariffline_{flow_code.replace(',', '_')}_{query_digest(cmd_codes)}"
    return Path(raw_dir) / f"{stem}{suffix}.json.gz"


def write_snapshot(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = (
        pl.DataFrame(records, infer_schema_length=None)
        if records
        else pl.DataFrame({"_empty": pl.Series([], dtype=pl.Boolean)})
    )
    frame.write_parquet(path, compression="zstd")


def valid_snapshot(path: Path) -> bool:
    """校验断点文件可读，避免坏文件被智能采集直接跳过。"""
    try:
        if path.name.endswith(".parquet"):
            pl.read_parquet(path)
            return True
        with gzip.open(path, "rt", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)
    except (OSError, json.JSONDecodeError, TypeError, pl.exceptions.PolarsError):
        return False


def append_manifest(
    raw_dir: Path,
    *,
    periods: list[str],
    flow_code: str,
    cmd_code: str,
    status: TarifflineStatus,
    rows: int,
    snapshot_path: Path | None,
) -> None:
    """逐批追加状态，支持中断后审计和恢复。"""
    manifest_path = raw_dir / "tariffline_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "collected_at": datetime.now(UTC).isoformat(),
        "periods": periods,
        "flow_code": flow_code,
        "cmd_code": cmd_code,
        "status": status,
        "rows": rows,
        "snapshot_path": str(snapshot_path) if snapshot_path else "",
    }
    with manifest_path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "append_manifest",
    "legacy_snapshot_path",
    "query_digest",
    "snapshot_path",
    "valid_snapshot",
    "write_snapshot",
]
