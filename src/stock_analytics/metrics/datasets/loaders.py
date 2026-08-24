"""指标层统一取数封装。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_analytics.catalog_compat import load_dataset_compat

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence
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
    reference: bool = False,
) -> pl.DataFrame:
    """通过 DataCatalog 加载指标依赖数据集，并在上下文内缓存。

    ``reference=True`` 表示静态参照表（如 ``opt_basic`` 期权合约属性），
    不随上下文日期窗口过滤，仅按需投影列。
    """
    if reference:
        actual_start = start_date
        actual_end = end_date
    else:
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

    base_key = context.cache_key(
        actual_data_source,
        dataset,
        "reference" if reference else actual_start,
        actual_end if not reference else None,
    )
    if base_key in context.cache:
        return _project_cached_frame(context.cache[base_key], columns)

    cached = _find_cached_projection(context.cache, base_key, columns)
    if cached is not None:
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


def _project_cached_frame(
    frame: pl.DataFrame,
    columns: Sequence[str] | None,
) -> pl.DataFrame:
    if columns is None or frame.is_empty():
        return frame
    return frame.select([column for column in columns if column in frame.columns])


def _find_cached_projection(
    cache: MutableMapping[str, pl.DataFrame],
    base_key: str,
    columns: Sequence[str] | None,
) -> pl.DataFrame | None:
    if columns is None:
        return None
    requested = set(columns)
    prefix = f"{base_key}:"
    for key, frame in cache.items():
        if (key == base_key or key.startswith(prefix)) and requested.issubset(frame.columns):
            return _project_cached_frame(frame, columns)
    return None
