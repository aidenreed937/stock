"""构建阶段的 MetricEngine 事实提取。

该模块只用于物化派生事实 Mart。报告读取路径不导入本模块，也不会在运行时
回退调用 MetricEngine。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.engine import MetricEngine
from stock_analytics.pipelines.market_temperature import metric_windows
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.facts_mart import (
    date_values,
    try_get_market_daily_fact,
)

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import (
        DimensionConfig,
        MetricInputConfig,
    )


def collect_metric_engine_rows(
    dimensions: Iterable[DimensionConfig],
    *,
    as_of_date: date,
    expected_trade_date: date,
    storage_dir: Path | str | None,
    market_daily: pl.DataFrame | None,
    dataset_cache: DatasetFrameCache | None,
    metric_contexts: dict[int, MetricContext] | None = None,
) -> list[dict[str, Any]]:
    """在 Mart 构建阶段提取配置中的 MetricEngine 指标事实。"""
    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    if market_daily is None:
        market_daily = store.get_market_daily(end_date=as_of_date)
    else:
        market_daily = market_daily.filter(pl.col("trade_date") <= as_of_date)

    from stock_data.catalog import DataCatalog

    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    engine = MetricEngine()
    contexts = metric_contexts if metric_contexts is not None else {}
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        for metric in dimension.metrics:
            if not metric.enabled or metric.source != "metric_engine":
                continue
            fact = try_get_market_daily_fact(
                market_daily,
                dimension.id,
                metric,
                as_of_date,
                expected_trade_date,
            )
            if fact is not None:
                rows.append(fact)
                continue
            context = metric_windows.context_for_metric(
                contexts,
                engine,
                catalog,
                as_of_date,
                metric.metric_id,
                dataset_cache=dataset_cache,
            )
            rows.append(_compute_metric_fact(engine, context, dimension.id, metric, as_of_date))
    return rows


def _compute_metric_fact(
    engine: MetricEngine,
    context: MetricContext,
    dimension: str,
    metric: MetricInputConfig,
    as_of_date: date,
) -> dict[str, Any]:
    try:
        result = engine.compute([metric.metric_id], context=context)[0]
        frame = result.frame
        if frame.is_empty() or metric.metric_id not in frame.columns:
            return _metric_fact(metric, dimension, as_of_date, "insufficient", "指标无可用输出")
        latest_date = _latest_metric_date(frame, as_of_date)
        if latest_date is None:
            return _metric_fact(metric, dimension, as_of_date, "insufficient", "指标无最新日期")
        latest_frame = frame.filter(pl.col("trade_date") == latest_date)
        if latest_frame.is_empty():
            return _metric_fact(metric, dimension, as_of_date, "insufficient", "指标无最新日期")
        value = _aggregate_metric(latest_frame, metric.metric_id, metric.aggregation)
        if value is None:
            return _metric_fact(metric, dimension, as_of_date, "insufficient", "指标值为空")
        return _metric_fact(
            metric,
            dimension,
            as_of_date,
            "ok",
            f"metric_date={latest_date.isoformat()}; aggregation={metric.aggregation}",
            value_float=value,
            sample_size=latest_frame.height,
        )
    except Exception as exc:
        return _metric_fact(
            metric,
            dimension,
            as_of_date,
            "error",
            f"{type(exc).__name__}: {exc}",
        )


def _latest_metric_date(frame: pl.DataFrame, as_of_date: date) -> date | None:
    if "trade_date" not in frame.columns:
        return None
    metric_columns = [column for column in frame.columns if column != "trade_date"]
    if metric_columns:
        frame = frame.filter(
            pl.any_horizontal([pl.col(column).is_not_null() for column in metric_columns])
        )
    dates = date_values(
        frame.filter(pl.col("trade_date") <= as_of_date)["trade_date"]
        .drop_nulls()
        .unique()
        .to_list()
    )
    return max(dates) if dates else None


def _aggregate_metric(frame: pl.DataFrame, metric_id: str, aggregation: str) -> float | None:
    values = frame.select(pl.col(metric_id).cast(pl.Float64, strict=False)).drop_nulls()
    if values.is_empty():
        return None
    if aggregation == "mean":
        value = values.select(pl.col(metric_id).mean()).item()
    elif aggregation == "median":
        value = values.select(pl.col(metric_id).median()).item()
    else:
        value = values[metric_id][-1]
    return float(value) if value is not None else None


def _metric_fact(
    metric: MetricInputConfig,
    dimension: str,
    as_of_date: date,
    status: str,
    note: str,
    *,
    value_float: float | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    return {
        "fact_id": f"metric.{dimension}.{metric.metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "metric_engine",
        "dataset": "",
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric.metric_id,
        "value_float": value_float,
        "value_text": "",
        "unit": "raw",
        "sample_size": sample_size,
        "source": "MetricEngine.compute (mart build)",
        "status": status,
        "note": note,
    }


__all__ = ["collect_metric_engine_rows"]
