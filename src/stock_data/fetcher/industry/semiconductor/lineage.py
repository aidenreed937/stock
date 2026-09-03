"""半导体源端快照对账工具。"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Any


def raw_content_sha256(content: bytes) -> str:
    """对源站返回的原始 bytes 计算稳定 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def response_content_bytes(response: Any) -> bytes:
    """从 HTTP response 提取原始 bytes，测试 mock 缺少 content 时回退到 text。"""
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        return content
    if isinstance(content, str) and content:
        return content.encode("utf-8")
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.encode("utf-8")
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    return bytes(content or b"")


def raw_snapshot_path_value(snapshot_path: Path, raw_root: Path) -> str:
    """保存可迁移的 RAW 快照路径，优先使用相对 raw_root 的路径。"""
    try:
        return str(snapshot_path.relative_to(raw_root))
    except ValueError:
        return str(snapshot_path)


def raw_snapshot_content_bytes(snapshot_path: Path) -> bytes:
    """读取普通或 gzip 压缩源端快照的未压缩原始内容。"""
    if str(snapshot_path).endswith(".gz"):
        with gzip.open(snapshot_path, "rb") as fh:
            return fh.read()
    return snapshot_path.read_bytes()
