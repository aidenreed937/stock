"""清理本地数据迁移临时文件、备份文件和恢复快照。"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MIGRATION_TEMP_SUFFIX = ".migration.tmp.parquet"
BACKUP_SUFFIX = ".bak.parquet"
RESTORE_DIR_PREFIX = "raw_unit_restore_"
SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class ArtifactCandidate:
    """待清理的数据产物。"""

    path: Path
    kind: str
    size_bytes: int
    mtime: float


def _file_kind(path: Path) -> str | None:
    if path.name.endswith(MIGRATION_TEMP_SUFFIX):
        return "migration_tmp"
    if path.name.endswith(BACKUP_SUFFIX):
        return "backup"
    return None


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def _candidate(path: Path, kind: str) -> ArtifactCandidate | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    size = _directory_size(path) if path.is_dir() else stat_result.st_size
    return ArtifactCandidate(
        path=path,
        kind=kind,
        size_bytes=size,
        mtime=stat_result.st_mtime,
    )


def _collect_restore_candidates(
    root: Path, cutoff: float
) -> tuple[list[ArtifactCandidate], list[Path]]:
    candidates: list[ArtifactCandidate] = []
    restore_dirs: list[Path] = []
    audit_dir = root / "audit"
    if not audit_dir.is_dir():
        return candidates, restore_dirs

    for path in sorted(audit_dir.iterdir()):
        if path.is_symlink() or not path.is_dir():
            continue
        if not path.name.startswith(RESTORE_DIR_PREFIX):
            continue
        item = _candidate(path, "restore_snapshot")
        if item is not None and item.mtime <= cutoff:
            candidates.append(item)
            restore_dirs.append(path)
    return candidates, restore_dirs


def _collect_file_candidates(
    root: Path, cutoff: float, restore_dirs: list[Path]
) -> list[ArtifactCandidate]:
    candidates: list[ArtifactCandidate] = []
    for path in root.rglob("*.parquet"):
        if path.is_symlink() or not path.is_file():
            continue
        if any(path.is_relative_to(restore_dir) for restore_dir in restore_dirs):
            continue
        kind = _file_kind(path)
        if kind is None:
            continue
        item = _candidate(path, kind)
        if item is not None and item.mtime <= cutoff:
            candidates.append(item)
    return candidates


def collect_candidates(
    root: Path | str = "data",
    older_than_days: float = 7.0,
    *,
    now: float | None = None,
) -> list[ArtifactCandidate]:
    """收集超过指定保留期的临时文件、备份文件和恢复快照。"""
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"数据根目录不存在: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"数据根路径不是目录: {root_path}")
    if older_than_days < 0:
        raise ValueError("older_than_days 不能小于 0")

    current_time = time.time() if now is None else now
    cutoff = current_time - older_than_days * SECONDS_PER_DAY

    restore_candidates, restore_dirs = _collect_restore_candidates(root_path, cutoff)
    candidates = restore_candidates + _collect_file_candidates(root_path, cutoff, restore_dirs)

    return sorted(candidates, key=lambda item: item.path.as_posix())


def delete_candidates(
    candidates: list[ArtifactCandidate],
    *,
    root: Path | str,
    cutoff: float,
) -> tuple[int, int]:
    """删除候选产物，并跳过扫描后重新变新的路径。"""
    root_path = Path(root).expanduser().resolve()
    deleted = 0
    skipped = 0
    for item in candidates:
        path = item.path
        if not path.resolve().is_relative_to(root_path):
            raise ValueError(f"候选路径超出数据根目录: {path}")
        try:
            if path.is_symlink() or path.stat().st_mtime > cutoff:
                skipped += 1
                continue
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            else:
                skipped += 1
                continue
        except FileNotFoundError:
            skipped += 1
            continue
        deleted += 1
    return deleted, skipped


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def _write_line(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def _print_summary(candidates: list[ArtifactCandidate], root: Path) -> None:
    labels = {
        "migration_tmp": "migration 临时文件",
        "backup": "Parquet 备份文件",
        "restore_snapshot": "RAW 恢复快照目录",
    }
    _write_line(f"数据根目录: {root}")
    total_size = _format_size(sum(item.size_bytes for item in candidates))
    _write_line(f"候选总数: {len(candidates)}，总大小: {total_size}")
    for kind, label in labels.items():
        selected = [item for item in candidates if item.kind == kind]
        if selected:
            size = _format_size(sum(item.size_bytes for item in selected))
            _write_line(f"- {label}: {len(selected)} 个，{size}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理本地 Parquet 临时文件、备份和恢复快照")
    parser.add_argument("--root", default="data", help="数据根目录，默认 data")
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=7.0,
        help="只处理超过该天数的产物，默认 7；传 0 可处理当前已有产物",
    )
    parser.add_argument("--apply", action="store_true", help="执行删除；默认只预览")
    parser.add_argument("--verbose", action="store_true", help="逐项打印候选路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行清理命令。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.older_than_days < 0:
        parser.error("--older-than-days 不能小于 0")

    root = Path(args.root).expanduser().resolve()
    now = time.time()
    cutoff = now - args.older_than_days * SECONDS_PER_DAY
    try:
        candidates = collect_candidates(root, args.older_than_days, now=now)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        parser.error(str(exc))

    _print_summary(candidates, root)
    if args.verbose:
        for item in candidates:
            _write_line(f"  [{item.kind}] {item.path.relative_to(root)}")

    if not args.apply:
        _write_line("预览模式，未删除任何文件。需要执行删除时追加 --apply。")
        return 0

    deleted, skipped = delete_candidates(candidates, root=root, cutoff=cutoff)
    _write_line(f"已删除: {deleted} 个；跳过: {skipped} 个。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
