"""指标层统一取数封装。"""

from datetime import date

import polars as pl

from stock.analytics.metrics.context import MetricContext


def load_metric_dataset(
    context: MetricContext,
    dataset: str,
    *,
    data_source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """通过 DataCatalog 加载指标依赖数据集，并在上下文内缓存。"""
    actual_start = start_date or context.start_date
    actual_end = end_date or context.resolve_end_date()
    actual_data_source = data_source or context.catalog.data_source
    cache_key = context.cache_key(actual_data_source, dataset, actual_start, actual_end)
    if cache_key not in context.cache:
        catalog = context.catalog
        if actual_data_source != context.catalog.data_source:
            catalog = type(context.catalog)(
                data_source=actual_data_source,
                storage_dir=context.catalog.storage_dir,
            )
        context.cache[cache_key] = catalog.load_dataset(
            dataset,
            start_date=actual_start,
            end_date=actual_end,
        )
    return context.cache[cache_key]
