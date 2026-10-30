"""垂直产业 RAW 原始快照读写边界。"""

from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import read_raw_text, save_raw_snapshot


def save_raw_artifact(
    source_name: str,
    filename: str,
    content: str | bytes | dict[str, Any] | list[Any],
    base_dir: Path,
    compress: bool = False,
) -> Path:
    """保存源端原始内容，不做清洗、聚合或派生计算。"""
    return save_raw_snapshot(source_name, filename, content, base_dir=base_dir, compress=compress)


def read_raw_artifact(path: Path) -> str:
    """读取源端原始文本快照。"""
    return read_raw_text(path)
