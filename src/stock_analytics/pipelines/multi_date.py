"""多日期市场分析产物的串行共享上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from stock_analytics.features.store import FeatureStore
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.engine import MetricEngine
from stock_analytics.pipelines.industry_structure import run_industry_structure
from stock_analytics.pipelines.investor_brief import run_investor_brief
from stock_analytics.pipelines.market_temperature import run_market_temperature
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.facts_mart import MARKET_DAILY_FACT_COLUMNS
from stock_analytics.pipelines.market_temperature.metric_windows import metric_lookback_days
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.market_temperature.config import (
    load_market_temperature_config,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class MultiDateArtifactSummary:
    """单个日期生成的三类产物路径摘要。"""

    as_of_date: date
    market_temperature_run_dir: Path
    industry_structure_run_dir: Path
    investor_brief_run_dir: Path


def run_multi_date_artifacts(
    dates: Sequence[date],
    *,
    storage_dir: Path | str | None = None,
    update_latest: bool = False,
    collect_metric_values: bool | None = None,
) -> tuple[MultiDateArtifactSummary, ...]:
    """串行生成多日期三类产物，并共享 Mart 与数据集读取缓存。

    Mart 由调用方在批量任务前重建一次；本函数只读取同一份
    ``market_daily``，不会在每个日期再次构建或重复读取原始数据集。
    """
    unique_dates = tuple(sorted(set(dates)))
    if not unique_dates:
        raise ValueError("多日期产物生成至少需要一个日期")

    storage_path = Path(storage_dir) if storage_dir is not None else None
    max_date = unique_dates[-1]
    market_dates = _load_trade_dates(
        "stock_daily_bar",
        unique_dates[0],
        max_date,
        storage_path,
        extra_window=20,
    )
    industry_dates = _load_trade_dates(
        "sw_daily",
        unique_dates[0],
        max_date,
        storage_path,
        extra_window=120,
    )
    mart_dir = storage_path / "mart" if storage_path is not None else None
    mart_start = unique_dates[0] - timedelta(days=1250 * 4)
    market_daily = FeatureStore(mart_dir=mart_dir).get_market_daily(
        start_date=mart_start,
        end_date=max_date,
        columns=MARKET_DAILY_FACT_COLUMNS,
    )
    dataset_cache = DatasetFrameCache(end_date=max_date)
    metric_contexts = _build_metric_contexts(
        unique_dates,
        storage_path,
        dataset_cache,
    )

    summaries: list[MultiDateArtifactSummary] = []
    for target_date in unique_dates:
        market_window = _window_until(market_dates, target_date, 20)
        industry_window = _window_until(industry_dates, target_date, 120)
        market_result = run_market_temperature(
            target_date=target_date,
            storage_dir=storage_path,
            update_latest=update_latest,
            collect_metric_values=collect_metric_values,
            market_daily=market_daily,
            dataset_cache=dataset_cache,
            trade_dates=market_window,
            metric_contexts=metric_contexts,
        )
        industry_result = run_industry_structure(
            target_date=target_date,
            storage_dir=storage_path,
            update_latest=update_latest,
            dataset_cache=dataset_cache,
            trade_dates=industry_window,
        )
        brief_result = run_investor_brief(
            target_date=target_date,
            update_latest=update_latest,
        )
        summaries.append(
            MultiDateArtifactSummary(
                as_of_date=target_date,
                market_temperature_run_dir=market_result.paths.run_dir,
                industry_structure_run_dir=industry_result.paths.run_dir,
                investor_brief_run_dir=brief_result.paths.run_dir,
            )
        )
        del market_result, industry_result, brief_result

    return tuple(summaries)


def _load_trade_dates(
    dataset: str,
    start_date: date,
    end_date: date,
    storage_dir: Path | None,
    *,
    extra_window: int,
) -> tuple[date, ...]:
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    scan_start = start_date - timedelta(days=extra_window * 4)
    count = max((end_date - scan_start).days + 5, extra_window)
    values = catalog.latest_trade_dates(dataset=dataset, n=count)
    return tuple(sorted(value for value in values if scan_start <= value <= end_date))


def _window_until(values: Sequence[date], target_date: date, window: int) -> tuple[date, ...]:
    selected = tuple(value for value in values if value <= target_date)
    if not selected:
        raise ValueError(f"{target_date.isoformat()} 没有可用交易日窗口")
    return selected[-window:]


def _build_metric_contexts(
    target_dates: Sequence[date],
    storage_dir: Path | None,
    dataset_cache: DatasetFrameCache,
) -> dict[int, MetricContext]:
    """为批次预建按历史窗口复用的 MetricContext。"""
    config = load_market_temperature_config()
    engine = MetricEngine()
    metric_ids = {
        metric.metric_id
        for dimension in config.dimensions
        for metric in dimension.metrics
        if metric.enabled and metric.source == "metric_engine"
    }
    if not metric_ids:
        return {}
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    contexts: dict[int, MetricContext] = {}
    for metric_id in sorted(metric_ids):
        lookback = metric_lookback_days(engine, metric_id)
        contexts.setdefault(
            lookback,
            MetricContext(
                catalog=catalog,
                target_date=target_dates[-1],
                start_date=target_dates[0] - timedelta(days=lookback),
                end_date=target_dates[-1],
                dataset_cache=dataset_cache,
            ),
        )
    return contexts


__all__ = ["MultiDateArtifactSummary", "run_multi_date_artifacts"]
