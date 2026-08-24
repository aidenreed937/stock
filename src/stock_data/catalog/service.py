"""统一读取本地已落盘 Curated Parquet 数据的数据目录服务 (DataCatalog)。"""

from __future__ import annotations

from pathlib import Path

from stock_data.catalog.compat import load_dataset_compat
from stock_data.catalog.service_methods import CatalogReadMixin
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import data_settings

_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")

__all__ = ["DataCatalog", "load_dataset_compat"]


class DataCatalog(CatalogReadMixin):
    """按数据源隔离的本地落盘数据统一读取入口。"""

    def __init__(
        self,
        data_source: str | None = None,
        storage_dir: Path | str | None = None,
        *,
        runtime: DataRuntimeContext | None = None,
    ) -> None:
        self.data_source = data_source or data_settings.data_source_mode
        self.runtime = runtime or data_settings.runtime_context
        self.storage_dir = (
            Path(storage_dir) if storage_dir is not None else self.runtime.curated_root
        )
        if not self.storage_dir.exists():
            raise FileNotFoundError(f"Curated 数据目录不存在: {self.storage_dir}")
