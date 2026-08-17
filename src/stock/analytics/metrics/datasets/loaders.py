"""指标层统一取数封装。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    import polars as pl

    from stock.analytics.metrics.context import MetricContext


def load_metric_dataset(  # noqa: PLR0913
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
    actual_data_source = data_source or context.catalog.data_source

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
        catalog = context.catalog
        if actual_data_source != context.catalog.data_source:
            catalog = type(context.catalog)(
                data_source=actual_data_source,
                storage_dir=context.catalog.storage_dir,
            )
        try:
            context.cache[cache_key] = catalog.load_dataset(
                dataset,
                start_date=actual_start,
                end_date=actual_end,
                columns=columns,
            )
        except TypeError:
            context.cache[cache_key] = catalog.load_dataset(
                dataset,
                start_date=actual_start,
                end_date=actual_end,
            )
    return context.cache[cache_key]
