"""市场温度计派生事实 Mart 的构建步骤。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.derived import collect_derived_metric_rows
from stock_analytics.pipelines.market_temperature.derived_options import _latest_dataset_date
from stock_analytics.pipelines.market_temperature.facts import (
    FACT_SCHEMA,
    _normalize_metric_dates,
)
from stock_analytics.pipelines.market_temperature.metric_facts import (
    collect_metric_engine_rows,
)
from stock_analytics.pipelines.market_temperature.short_term import collect_short_term_rows
from stock_reporting.interpretation.market_temperature.config import (
    MarketTemperatureConfig,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog


MARKET_TEMPERATURE_DERIVED_FACTS_MART_NAME = "market_temperature_derived_facts"
_MARKET_DAILY_OPTION_COLUMNS = frozenset(
    {
        "trade_date",
        "option_put_call_volume_ratio",
        "option_put_call_oi_ratio",
        "option_amount",
        "option_open_interest",
        "option_near_month_amount_share",
    }
)


def empty_market_temperature_derived_facts() -> pl.DataFrame:
    """返回稳定 schema 的空派生事实 Mart。"""
    return pl.DataFrame(schema=FACT_SCHEMA)


def build_market_temperature_derived_facts_mart(
    catalog: MarketDataCatalog,
    store: FeatureStore,
    config: MarketTemperatureConfig,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    """在构建阶段一次计算并保存市场温度所需的全部事实。

    这里是唯一允许使用 MetricEngine 和 DataCatalog 派生逻辑的构建入口；
    报告运行只读取本 Mart。
    """
    effective_start = _incremental_start(
        store,
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    market_daily = _load_market_daily(store, start_date=effective_start, end_date=end_date)
    if market_daily.is_empty() or "trade_date" not in market_daily.columns:
        return empty_market_temperature_derived_facts()

    dates = _target_dates(market_daily, start_date=effective_start, end_date=end_date)
    if not dates:
        return empty_market_temperature_derived_facts()

    all_trade_dates = tuple(sorted(set(market_daily["trade_date"].drop_nulls().to_list())))
    lookback_cache = dataset_cache or DatasetFrameCache(end_date=dates[-1])
    market_daily_option_source_valid = _market_daily_option_source_is_current(
        catalog,
        store,
        market_daily,
        dataset_cache=lookback_cache,
    )
    rows: list[dict[str, Any]] = []
    max_window = max(config.main_window, *config.short_windows)
    for as_of_date in dates:
        trade_dates = tuple(value for value in all_trade_dates if value <= as_of_date)[-max_window:]
        if not trade_dates:
            continue
        expected_trade_date = trade_dates[-1]
        rows.extend(
            collect_metric_engine_rows(
                config.dimensions,
                as_of_date=as_of_date,
                expected_trade_date=expected_trade_date,
                storage_dir=getattr(catalog, "storage_dir", None),
                market_daily=market_daily,
                dataset_cache=lookback_cache,
            )
        )
        rows.extend(
            collect_derived_metric_rows(
                as_of_date=as_of_date,
                trade_dates=trade_dates,
                storage_dir=getattr(catalog, "storage_dir", None),
                dataset_cache=lookback_cache,
                external_cutoff_date=_external_cutoff(as_of_date, trade_dates),
                market_daily=market_daily,
                market_daily_option_source_valid=market_daily_option_source_valid,
            )
        )
        rows.extend(
            collect_short_term_rows(
                config.short_windows,
                as_of_date,
                getattr(catalog, "storage_dir", None),
                market_daily=market_daily,
            )
        )

    if not rows:
        return empty_market_temperature_derived_facts()
    result = pl.DataFrame(_normalize_metric_dates(rows), schema=FACT_SCHEMA)
    store.save_market_temperature_derived_facts(result, overwrite=overwrite)
    return result


def _market_daily_option_source_is_current(
    catalog: MarketDataCatalog,
    store: FeatureStore,
    market_daily: pl.DataFrame,
    *,
    dataset_cache: DatasetFrameCache,
) -> bool:
    """在批次开始时校验 market_daily 是否覆盖 opt_daily 源水位。"""
    if not _MARKET_DAILY_OPTION_COLUMNS.issubset(market_daily.columns):
        return False
    metadata = store.get_market_daily_metadata()
    source_watermarks = metadata.get("source_watermarks")
    if not isinstance(source_watermarks, dict):
        return False
    recorded = source_watermarks.get("opt_daily")
    if not isinstance(recorded, str) or recorded in {"", "missing"}:
        return False
    market_daily_end = market_daily["trade_date"].drop_nulls().max()
    if not isinstance(market_daily_end, date):
        return False
    try:
        current = _latest_dataset_date(
            catalog,
            "opt_daily",
            market_daily_end,
            dataset_cache,
        )
        recorded_date = date.fromisoformat(recorded)
    except (TypeError, ValueError):
        return False
    return current is not None and recorded_date >= current


def _load_market_daily(
    store: FeatureStore,
    *,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    lookback_start = start_date - timedelta(days=1250 * 4) if start_date is not None else None
    return store.get_market_daily(start_date=lookback_start, end_date=end_date)


def _target_dates(
    frame: pl.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, ...]:
    values = [value for value in frame["trade_date"].unique().to_list() if isinstance(value, date)]
    return tuple(
        sorted(
            value
            for value in values
            if (start_date is None or value >= start_date)
            and (end_date is None or value <= end_date)
        )
    )


def _external_cutoff(as_of_date: date, trade_dates: tuple[date, ...]) -> date:
    return max(
        (value for value in trade_dates if value < as_of_date),
        default=as_of_date - timedelta(days=1),
    )


def _incremental_start(
    store: FeatureStore,
    *,
    requested_start: date | None,
    end_date: date | None,
    overwrite: bool,
) -> date | None:
    if overwrite:
        return requested_start
    existing = store.get_domain_mart(
        MARKET_TEMPERATURE_DERIVED_FACTS_MART_NAME,
        date_column="as_of_date",
        columns=["as_of_date"],
    )
    if existing.is_empty() or "as_of_date" not in existing.columns:
        return requested_start
    latest = existing["as_of_date"].drop_nulls().max()
    if not isinstance(latest, date) or (end_date is not None and latest > end_date):
        return requested_start
    if requested_start is None or requested_start <= latest:
        return latest
    return requested_start


__all__ = [
    "MARKET_TEMPERATURE_DERIVED_FACTS_MART_NAME",
    "build_market_temperature_derived_facts_mart",
    "empty_market_temperature_derived_facts",
]
