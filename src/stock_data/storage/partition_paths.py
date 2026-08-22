"""Curated Parquet 分区路径查询辅助函数。"""

from datetime import date
from pathlib import Path

from stock_data.core.task_registry import get_endpoint_market
from stock_data.storage.compat import StorageCompat


def matching_curated_paths(
    storage_dir: Path,
    data_source: str,
    target_dataset: str,
    target_date: date,
    direct_path: Path,
) -> list[Path]:
    """返回目标日期对应的有效 Curated Parquet 文件。"""
    if direct_path.exists() and not StorageCompat.is_artifact_path(direct_path):
        return [direct_path]
    market_code = get_endpoint_market(data_source, target_dataset)
    dataset_dir = storage_dir / f"market={market_code.upper()}" / target_dataset
    if not dataset_dir.exists():
        return []
    month_dir = dataset_dir / f"year={target_date.year:04d}" / f"month={target_date.month:02d}"
    if not month_dir.exists():
        return []
    return [
        path for path in month_dir.glob("*.parquet") if not StorageCompat.is_artifact_path(path)
    ]


__all__ = ["matching_curated_paths"]
