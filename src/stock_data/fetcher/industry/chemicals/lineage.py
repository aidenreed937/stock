"""化工源端快照血缘工具。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def raw_content_sha256(content: bytes) -> str:
    """计算源端内容的稳定 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def raw_snapshot_path_value(snapshot_path: Path, raw_root: Path) -> str:
    """保存可迁移的相对 RAW 路径。"""
    try:
        return str(snapshot_path.relative_to(raw_root))
    except ValueError:
        return str(snapshot_path)
