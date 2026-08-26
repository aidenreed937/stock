"""按数据集身份选择物理 Parquet 文件。"""

from __future__ import annotations

from pathlib import Path

from stock_data.storage.compat import StorageCompat

_KNOWN_PROVIDERS = frozenset({"tushare", "lixinger", "yfinance", "fred", "alphavantage"})


def path_contains_dataset(path: Path, dataset: str) -> bool:
    """判断物理路径是否属于指定数据集目录或扁平数据集文件。"""
    target = dataset.casefold()
    return any(part.casefold() == target for part in path.parts) or path.stem.casefold() == target


def matching_dataset_files(
    root: str | Path,
    aliases: set[str],
    canonical_dataset: str | None = None,
    data_source: str | None = None,
) -> list[Path]:
    """按别名匹配文件；存在规范文件时排除历史别名目录。"""
    base = Path(root)
    if not base.exists():
        return []
    files = [
        path
        for path in base.rglob("*.parquet")
        if not StorageCompat.is_artifact_path(path)
        and any(path_contains_dataset(path, alias) for alias in aliases)
    ]
    if data_source:
        source = data_source.casefold()
        files = [
            path
            for path in files
            if not (_KNOWN_PROVIDERS & {part.casefold() for part in path.parts})
            or source in {part.casefold() for part in path.parts}
        ]
    if canonical_dataset:
        canonical_files = [path for path in files if path_contains_dataset(path, canonical_dataset)]
        if canonical_files:
            return sorted(canonical_files)
    return sorted(files)
