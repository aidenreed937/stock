"""将 Tariffline RAW JSON.GZ 快照迁移为按批次保存的 Parquet。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.customs.collectors.tariffline import (
    _valid_snapshot,
    _write_snapshot,
    tariffline_snapshot_path,
)

DEFAULT_RAW_DIR = Path("data/raw/industry/customs/comtrade_tariffline")


@dataclass(frozen=True)
class MigrationPlan:
    """一个旧快照及其 Parquet 目标。"""

    source: Path
    target: Path
    rows: int
    source_content_sha256: str


def _resolve_snapshot_path(raw_dir: Path, value: Any) -> Path:
    candidate = Path(str(value or ""))
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return raw_dir / candidate


def _read_json_snapshot(path: Path) -> tuple[list[dict[str, Any]], str]:
    content = path.read_bytes()
    payload = json.loads(gzip.decompress(content))
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"JSON.GZ 快照 data 不是对象列表: {path}")
    return items, hashlib.sha256(content).hexdigest()


def _target_path(raw_dir: Path, entry: dict[str, Any]) -> Path:
    periods = [str(value) for value in entry.get("periods", [])]
    flow_code = str(entry.get("flow_code", ""))
    cmd_codes = str(entry.get("cmd_code", "")).split(",")
    if not periods or not flow_code or not any(cmd_codes):
        raise ValueError(f"Manifest 请求参数不完整: {entry}")
    return tariffline_snapshot_path(raw_dir, periods, flow_code, cmd_codes)


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _collect_plans(
    raw_dir: Path, entries: list[dict[str, Any]]
) -> tuple[list[MigrationPlan], list[Path]]:
    plans_by_source: dict[Path, MigrationPlan] = {}
    missing: list[Path] = []
    for entry in entries:
        if entry.get("status") != "success":
            continue
        snapshot_value = str(entry.get("snapshot_path", ""))
        if not snapshot_value.endswith(".json.gz"):
            continue
        source = _resolve_snapshot_path(raw_dir, snapshot_value).resolve()
        if source in plans_by_source:
            continue
        if not source.is_file():
            missing.append(source)
            continue
        items, source_hash = _read_json_snapshot(source)
        plans_by_source[source] = MigrationPlan(
            source=source,
            target=tariffline_snapshot_path(
                raw_dir, entry["periods"], entry["flow_code"], str(entry["cmd_code"]).split(",")
            ),
            rows=len(items),
            source_content_sha256=source_hash,
        )
    return list(plans_by_source.values()), missing


def _write_parquet(plan: MigrationPlan, items: list[dict[str, Any]]) -> None:
    target = plan.target
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        frame = pl.read_parquet(target)
        if frame.height != plan.rows:
            raise ValueError(f"目标 Parquet 行数不一致: {target}")
        return

    temporary = target.with_name(f".{target.stem}.tmp.parquet")
    try:
        _write_snapshot(temporary, items)
        if not _valid_snapshot(temporary) or pl.read_parquet(temporary).height != plan.rows:
            raise ValueError(f"Parquet 校验失败: {target}")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _rewrite_manifest(
    manifest_path: Path,
    entries: list[dict[str, Any]],
    plans: list[MigrationPlan],
) -> None:
    plan_by_source = {plan.source: plan for plan in plans}
    raw_dir = manifest_path.parent.resolve()
    updated: list[dict[str, Any]] = []
    for entry in entries:
        snapshot_value = str(entry.get("snapshot_path", ""))
        source = _resolve_snapshot_path(manifest_path.parent, snapshot_value).resolve()
        plan = plan_by_source.get(source)
        if plan is not None:
            try:
                plan.source.relative_to(raw_dir)
            except ValueError as exc:
                raise ValueError(f"迁移源文件不在 RAW 目录内: {plan.source}") from exc
            entry = dict(entry)
            entry["snapshot_path"] = str(plan.target)
            entry["source_content_sha256"] = plan.source_content_sha256
        updated.append(entry)

    temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file_obj:
            for entry in updated:
                file_obj.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(temporary, manifest_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def migrate(raw_dir: Path, *, apply: bool, remove_json: bool) -> int:
    manifest_path = raw_dir / "tariffline_manifest.jsonl"
    if not manifest_path.exists():
        print(f"Manifest 不存在: {manifest_path}")
        return 1
    if remove_json and not apply:
        print("--remove-json 必须和 --apply 一起使用")
        return 2

    entries = _load_manifest(manifest_path)
    plans, missing = _collect_plans(raw_dir, entries)
    if missing:
        print(f"缺失 JSON.GZ 快照 {len(missing)} 个，停止迁移")
        return 1
    print(f"待迁移快照: {len(plans)} 个，原始行数: {sum(plan.rows for plan in plans)}")
    if not apply:
        print("dry-run: 未写入 Parquet、未修改 Manifest、未删除 JSON.GZ")
        return 0

    for plan in plans:
        items, source_hash = _read_json_snapshot(plan.source)
        if source_hash != plan.source_content_sha256 or len(items) != plan.rows:
            raise ValueError(f"源快照在迁移期间发生变化: {plan.source}")
        _write_parquet(plan, items)

    _rewrite_manifest(manifest_path, entries, plans)
    if remove_json:
        for plan in plans:
            plan.source.unlink()
        print(f"已删除 JSON.GZ: {len(plans)} 个")
    print(f"Parquet 迁移完成: {len(plans)} 个，行数: {sum(plan.rows for plan in plans)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--apply", action="store_true", help="执行迁移；缺省仅 dry-run")
    parser.add_argument(
        "--remove-json",
        action="store_true",
        help="迁移并校验成功后删除已转换的 JSON.GZ",
    )
    args = parser.parse_args(argv)
    return migrate(args.raw_dir, apply=args.apply, remove_json=args.remove_json)


if __name__ == "__main__":
    raise SystemExit(main())
