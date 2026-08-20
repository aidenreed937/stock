"""指标层统一取数封装。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_analytics.catalog_compat import load_dataset_compat

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    import polars as pl

    from stock_analytics.metrics.context import MetricContext


def load_metric_dataset(
    context: MetricContext,
    dataset: str,
    *,
    data_source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """通过 DataCatalog 加载指标依赖数据集，并在上下文内缓存。"""
    actual_start = start_date or context.start_date
    actual_end = end_date or context.resolve_end_date()
    actual_data_source = data_source or getattr(context.catalog, "data_source", "tushare")

    catalog = context.catalog
    current_source = getattr(context.catalog, "data_source", "tushare")
    if actual_data_source != current_source:
        storage_dir = getattr(context.catalog, "storage_dir", None)
        from stock_data.catalog import DataCatalog

        catalog = DataCatalog(data_source=actual_data_source, storage_dir=storage_dir)

    if context.dataset_cache is not None:
        return context.dataset_cache.load(
            catalog,
            dataset,
            start_date=actual_start,
            end_date=actual_end,
            columns=columns,
        )

    base_key = context.cache_key(actual_data_source, dataset, actual_start, actual_end)
    if base_key in context.cache:
        cached = context.cache[base_key]
        if columns is not None and not cached.is_empty():
            selected = [c for c in columns if c in cached.columns]
            return cached.select(selected)
        return cached

    cache_key = (
        base_key
        if not columns
        else context.cache_key(
            actual_data_source,
            dataset,
            actual_start,
            actual_end,
            ",".join(sorted(columns)),
        )
    )

    if cache_key not in context.cache:
        context.cache[cache_key] = load_dataset_compat(
            catalog,
            dataset,
            start_date=actual_start,
            end_date=actual_end,
            columns=columns,
        )
    return context.cache[cache_key]
