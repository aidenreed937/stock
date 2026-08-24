"""DataCatalog 兼容加载器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from inspect import Parameter, signature
from typing import Any

import polars as pl


def load_dataset_compat(
    catalog: Any,
    dataset: str,
    *,
    columns: Sequence[str] | None = None,
    **kwargs: Any,
) -> pl.DataFrame:
    """按 loader 签名传递可用参数，并在需要时执行列投影。"""
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


__all__ = ["load_dataset_compat"]
