"""多日期市场分析产物的串行共享上下文。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.industry_structure import run_industry_structure
from stock_analytics.pipelines.investor_brief import run_investor_brief
from stock_analytics.pipelines.market_temperature import run_market_temperature
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.facts_mart import MARKET_DAILY_FACT_COLUMNS
from stock_analytics.pipelines.quant_brief import run_quant_brief
from stock_data.catalog import DataCatalog


@dataclass(frozen=True, slots=True)
class MultiDateArtifactSummary:
    """单个日期生成的四类产物路径摘要。"""

    as_of_date: date
    market_temperature_run_dir: Path
    industry_structure_run_dir: Path
    investor_brief_run_dir: Path
    quant_brief_run_dir: Path


def run_multi_date_artifacts(
    dates: Sequence[date],
    *,
    storage_dir: Path | str | None = None,
    analytics_root: Path | str | None = None,
    update_latest: bool = False,
    run_class: RunClass = "official",
    collect_metric_values: bool | None = None,
) -> tuple[MultiDateArtifactSummary, ...]:
    """串行生成多日期四类产物，并共享 Mart 与数据集读取缓存。"""
    unique_dates = tuple(sorted(set(dates)))
    if not unique_dates:
        raise ValueError("多日期产物生成至少需要一个日期")

    storage_path = Path(storage_dir) if storage_dir is not None else None
    analytics_path = Path(analytics_root) if analytics_root is not None else None
    max_date = unique_dates[-1]
    dataset_cache = DatasetFrameCache(end_date=max_date)
    market_dates = _load_trade_dates(
        "stock_daily_bar",
        unique_dates[0],
        max_date,
        storage_path,
        extra_window=20,
        dataset_cache=dataset_cache,
    )
    industry_dates = _load_trade_dates(
        "sw_daily",
        unique_dates[0],
        max_date,
        storage_path,
        extra_window=120,
        dataset_cache=dataset_cache,
    )
    mart_dir = storage_path / "mart" if storage_path is not None else None
    mart_start = unique_dates[0] - timedelta(days=1250 * 4)
    market_daily = FeatureStore(mart_dir=mart_dir).get_market_daily(
        start_date=mart_start,
        end_date=max_date,
        columns=MARKET_DAILY_FACT_COLUMNS,
    )

    summaries: list[MultiDateArtifactSummary] = []
    for target_date in unique_dates:
        market_window = _window_until(market_dates, target_date, 20)
        industry_window = _window_until(industry_dates, target_date, 120)
        market_result = run_market_temperature(
            target_date=target_date,
            storage_dir=storage_path,
            output_root=(
                analytics_path / "market_temperature" if analytics_path is not None else None
            ),
            run_class=run_class,
            update_latest=update_latest,
            collect_metric_values=collect_metric_values,
            market_daily=market_daily,
            dataset_cache=dataset_cache,
            trade_dates=market_window,
        )
        industry_result = run_industry_structure(
            target_date=target_date,
            storage_dir=storage_path,
            output_root=(
                analytics_path / "industry_structure" if analytics_path is not None else None
            ),
            run_class=run_class,
            update_latest=update_latest,
            dataset_cache=dataset_cache,
            trade_dates=industry_window,
        )
        brief_result = run_investor_brief(
            target_date=target_date,
            market_run_id=market_result.paths.run_dir.name,
            industry_run_id=industry_result.paths.run_dir.name,
            output_root=analytics_path / "investor_brief" if analytics_path is not None else None,
            market_temperature_root=(
                analytics_path / "market_temperature" if analytics_path is not None else None
            ),
            industry_structure_root=(
                analytics_path / "industry_structure" if analytics_path is not None else None
            ),
            run_class=run_class,
            update_latest=update_latest,
        )
        quant_result = run_quant_brief(
            target_date=target_date,
            market_run_id=market_result.paths.run_dir.name,
            industry_run_id=industry_result.paths.run_dir.name,
            storage_dir=storage_path,
            output_root=analytics_path / "quant_brief" if analytics_path is not None else None,
            market_temperature_root=(
                analytics_path / "market_temperature" if analytics_path is not None else None
            ),
            industry_structure_root=(
                analytics_path / "industry_structure" if analytics_path is not None else None
            ),
            run_class=run_class,
            update_latest=update_latest,
        )
        summaries.append(
            MultiDateArtifactSummary(
                as_of_date=target_date,
                market_temperature_run_dir=market_result.paths.run_dir,
                industry_structure_run_dir=industry_result.paths.run_dir,
                investor_brief_run_dir=brief_result.paths.run_dir,
                quant_brief_run_dir=quant_result.paths.run_dir,
            )
        )
        del market_result, industry_result, brief_result, quant_result

    return tuple(summaries)


def _load_trade_dates(
    dataset: str,
    start_date: date,
    end_date: date,
    storage_dir: Path | None,
    *,
    extra_window: int,
    dataset_cache: DatasetFrameCache | None = None,
) -> tuple[date, ...]:
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    if dataset_cache is not None:
        from stock_analytics.pipelines.market_temperature.cache import CachedCatalog

        catalog = CachedCatalog(catalog, dataset_cache)  # type: ignore[assignment]
    scan_start = start_date - timedelta(days=extra_window * 4)
    count = max((end_date - scan_start).days + 1, extra_window)
    values = catalog.latest_trade_dates(dataset=dataset, n=count)
    return tuple(sorted(value for value in values if scan_start <= value <= end_date))


def _window_until(values: Sequence[date], target_date: date, window: int) -> tuple[date, ...]:
    selected = tuple(value for value in values if value <= target_date)
    if not selected:
        raise ValueError(f"{target_date.isoformat()} 没有可用交易日窗口")
    return selected[-window:]


__all__ = ["MultiDateArtifactSummary", "run_multi_date_artifacts"]
