"""数据目录领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class CatalogDataset:
    """数据目录中一个数据集的定位信息。"""

    data_source: str
    dataset: str
    files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def total_rows(self) -> int | None:
        if not self.files:
            return None
        try:
            return int(
                sum(pl.scan_parquet(path).select(pl.len()).collect().item() for path in self.files)
            )
        except Exception:
            return None
