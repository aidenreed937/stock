"""申万行业成分版本化 Curated 表的读取兼容辅助。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import polars as pl

from stock_data.catalog.compat import load_dataset_compat

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog

INDEX_MEMBER_VERSIONED_DATASET = "index_member_versioned"
UNRESOLVED_SRC = "UNRESOLVED"


def load_index_member_for_classification(
    catalog: MarketDataCatalog,
    *,
    classification: str = "SW2021",
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """优先读取版本化成分表并筛选版本，缺表时兼容回退原始成分表。"""
    requested = tuple(dict.fromkeys(columns or ("index_code", "con_code", "in_date", "out_date")))
    if not callable(getattr(catalog, "list_datasets", None)):
        return _project_columns(
            _load_dataset(
                catalog,
                "index_member",
                tuple(column for column in requested if column != "src"),
            ),
            requested,
        )
    if _catalog_has_dataset(catalog, INDEX_MEMBER_VERSIONED_DATASET):
        probe_columns = tuple(dict.fromkeys((*requested, "src")))
        versioned = _load_dataset(catalog, INDEX_MEMBER_VERSIONED_DATASET, probe_columns)
        if "src" not in versioned.columns:
            return pl.DataFrame()
        selected = versioned.filter(pl.col("src").cast(pl.String, strict=False) == classification)
        return _project_columns(selected, requested)

    return _project_columns(
        _load_dataset(
            catalog,
            "index_member",
            tuple(column for column in requested if column != "src"),
        ),
        requested,
    )


def _load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    columns: Sequence[str],
) -> pl.DataFrame:
    try:
        return load_dataset_compat(catalog, dataset, columns=columns, dedup=False)
    except Exception:
        return pl.DataFrame()


def _catalog_has_dataset(catalog: MarketDataCatalog, dataset: str) -> bool:
    list_datasets = getattr(catalog, "list_datasets", None)
    if not callable(list_datasets):
        return False
    try:
        return dataset in list_datasets()
    except Exception:
        return False


def _project_columns(frame: pl.DataFrame, columns: Sequence[str]) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.select([column for column in columns if column in frame.columns])


__all__ = [
    "INDEX_MEMBER_VERSIONED_DATASET",
    "UNRESOLVED_SRC",
    "load_index_member_for_classification",
]
