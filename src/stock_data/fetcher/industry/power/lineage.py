"""光伏 RAW 文件血缘字段辅助函数。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def raw_content_sha256(content: bytes) -> str:
    """计算源端内容的稳定 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def raw_snapshot_path_value(snapshot_path: Path, raw_root: Path) -> str:
    """返回相对 RAW 根目录的可迁移快照路径。"""
    try:
        return str(snapshot_path.relative_to(raw_root))
    except ValueError:
        return str(snapshot_path)


def file_lineage(snapshot_path: Path, raw_root: Path) -> tuple[str, str]:
    """读取本地 RAW 文件并返回 ``(sha256, relative_path)``。"""
    if not snapshot_path.exists():
        return "", ""
    return (
        raw_content_sha256(snapshot_path.read_bytes()),
        raw_snapshot_path_value(snapshot_path, raw_root),
    )


__all__ = ["file_lineage", "raw_content_sha256", "raw_snapshot_path_value"]
