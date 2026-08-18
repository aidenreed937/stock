"""DataCatalog 的目录摘要构建工具。"""

from __future__ import annotations

from typing import Any

import polars as pl


def build_catalog_description(catalog: Any, market: str | None = None) -> pl.DataFrame:
    """生成数据目录摘要（数据集、文件数、总行数）。"""
    rows = [
        {
            "data_source": catalog.data_source,
            "dataset": entry.dataset,
            "files": len(entry.files),
            "rows": entry.total_rows,
        }
        for entry in catalog.available_datasets(market=market)
    ]
    return (
        pl.DataFrame(rows)
        if rows
        else pl.DataFrame(
            schema={
                "data_source": pl.Utf8,
                "dataset": pl.Utf8,
                "files": pl.Int64,
                "rows": pl.Int64,
            }
        )
    )
