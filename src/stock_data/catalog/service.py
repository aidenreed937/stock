"""统一读取本地已落盘 Curated Parquet 数据的数据目录服务 (DataCatalog)。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.catalog.service_methods import CatalogReadMixin
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import data_settings

_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")


def load_dataset_compat(
    catalog: Any,
    dataset: str,
    *,
    columns: Sequence[str] | None = None,
    **kwargs: Any,
) -> pl.DataFrame:
    """按加载器签名传递可用参数，并在需要时执行列投影。"""
    loader = catalog.load_dataset
    parameters: Mapping[str, Parameter]
    try:
        parameters = signature(loader).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    call_kwargs = {
        key: value
        for key, value in kwargs.items()
        if (key in parameters or accepts_kwargs) and value is not None
    }
    if columns is not None and ("columns" in parameters or accepts_kwargs):
        call_kwargs["columns"] = columns

    frame = loader(dataset, **call_kwargs)
    if not isinstance(frame, pl.DataFrame):
        return pl.DataFrame()
    if columns is not None and not frame.is_empty():
        return frame.select([column for column in columns if column in frame.columns])
    return frame


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
