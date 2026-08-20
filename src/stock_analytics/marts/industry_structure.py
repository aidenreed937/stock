"""申万行业日频与结构面板事实 Mart 的构建步骤。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock_analytics.pipelines.industry_structure.panel import (
    BASE_PANEL_SCHEMA,
    _industry_daily_frame,
    build_industry_panel_from_daily,
)
from stock_analytics.pipelines.industry_structure.panel_batch import _market_panel_batch
from stock_analytics.pipelines.industry_structure.panel_batch_inputs import (
    IndustryPanelBatchInputs,
)
from stock_analytics.pipelines.industry_structure.panel_metrics import (
    historical_percentile,
    with_market_columns,
    with_return_columns,
)
from stock_analytics.pipelines.market_temperature.cache import CachedCatalog, DatasetFrameCache
from stock_core.contracts import MarketDataCatalog
from stock_data.catalog import DataCatalog

if TYPE_CHECKING:
    from stock_analytics.features.store import FeatureStore
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


INDUSTRY_DAILY_MART_NAME = "industry_daily"
INDUSTRY_PANEL_DAILY_MART_NAME = "industry_panel_daily"

INDUSTRY_DAILY_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "classification": pl.Utf8,
    "industry_level": pl.Utf8,
    "close": pl.Float64,
    "amount": pl.Float64,
    "amount_yi": pl.Float64,
    "return_5d": pl.Float64,
    "return_10d": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "return_120d": pl.Float64,
    "ma_bias_20d": pl.Float64,
    "tcr": pl.Float64,
    "tcr_percentile": pl.Float64,
}


def empty_industry_daily() -> pl.DataFrame:
    """返回稳定 schema 的空行业日频 Mart。"""
    return pl.DataFrame(schema=INDUSTRY_DAILY_SCHEMA)


def build_industry_daily_frame(
    raw_sw: pl.DataFrame,
    config: IndustryStructureConfig,
    catalog: MarketDataCatalog,
) -> pl.DataFrame:
    """从一次性加载的 ``sw_daily`` 计算行业日频事实。"""
    base = _industry_daily_frame(raw_sw, config, catalog)
    if base.is_empty():
        return empty_industry_daily()

    windows = tuple(sorted({5, 10, 20, 60, 120, *config.windows}))
    daily = with_return_columns(base, windows)
    daily = with_market_columns(daily, config.main_window)
    daily = daily.with_columns(
        (pl.col("amount") / 1e8).alias("amount_yi"),
        pl.col("tcr").cast(pl.Float64, strict=False).alias("tcr"),
    )
    daily = _add_tcr_percentile(daily)
    selected = [column for column in INDUSTRY_DAILY_SCHEMA if column in daily.columns]
    result = daily.select(selected)
    missing = [
        pl.lit(None, dtype=dtype).alias(column)
        for column, dtype in INDUSTRY_DAILY_SCHEMA.items()
        if column not in result.columns
    ]
    if missing:
        result = result.with_columns(missing)
    return result.select(list(INDUSTRY_DAILY_SCHEMA)).sort(["trade_date", "industry_code"])


def build_industry_daily_mart(
    catalog: MarketDataCatalog,
    store: FeatureStore,
    config: IndustryStructureConfig,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    dataset_cache: DatasetFrameCache | None = None,
    return_lookback: bool = False,
) -> pl.DataFrame:
    """加载一次申万行情并物化行业日频 Mart。"""
    effective_start = _incremental_start(
        store,
        INDUSTRY_DAILY_MART_NAME,
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
    )
    calc_start = _with_lookback(effective_start, config)
    columns = [
        "symbol",
        "trade_date",
        "name",
        "industry_name",
        "index_name",
        "close",
        "amount",
        "classification",
        "industry_level",
    ]
    raw = _load_dataset(
        catalog,
        "sw_daily",
        start_date=calc_start,
        end_date=end_date,
        columns=columns,
        dataset_cache=dataset_cache,
    )
    result = build_industry_daily_frame(raw, config, catalog)
    if result.is_empty():
        return result
    full_result = result
    if effective_start is not None:
        result = result.filter(pl.col("trade_date") >= effective_start)
    if end_date is not None:
        result = result.filter(pl.col("trade_date") <= end_date)
    if not result.is_empty():
        store.save_industry_daily(result, overwrite=overwrite)
    return full_result if return_lookback else result


def build_industry_panel_daily_mart(
    catalog: MarketDataCatalog,
    store: FeatureStore,
    config: IndustryStructureConfig,
    *,
    start_date: date | None,
    end_date: date | None,
    overwrite: bool,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    """从 ``industry_daily`` 与 Curated 基本面输入物化逐日行业面板。"""
    effective_start = _incremental_start(
        store,
        INDUSTRY_PANEL_DAILY_MART_NAME,
        requested_start=start_date,
        end_date=end_date,
        overwrite=overwrite,
        date_column="as_of_date",
    )
    daily_result = build_industry_daily_mart(
        catalog,
        store,
        config,
        start_date=effective_start,
        end_date=end_date,
        overwrite=overwrite,
        dataset_cache=dataset_cache,
        return_lookback=True,
    )
    daily = daily_result
    stored_daily = store.get_industry_daily(
        start_date=_with_lookback(effective_start, config), end_date=end_date
    )
    if not stored_daily.is_empty():
        daily = (
            pl.concat([daily, stored_daily], how="diagonal_relaxed")
            .unique(subset=["trade_date", "industry_code"], keep="last")
            .sort(["trade_date", "industry_code"])
        )
    if daily.is_empty() or "trade_date" not in daily.columns:
        return pl.DataFrame(schema=BASE_PANEL_SCHEMA)

    target_dates = _target_dates(daily, start_date=effective_start, end_date=end_date)
    if not target_dates:
        return pl.DataFrame(schema=BASE_PANEL_SCHEMA)

    cache = dataset_cache or DatasetFrameCache(end_date=end_date)
    cat_ts = CachedCatalog(catalog, cache)
    cat_lx = CachedCatalog(
        DataCatalog(data_source="lixinger", storage_dir=getattr(catalog, "storage_dir", None)),
        cache,
    )
    panels: list[pl.DataFrame] = []
    all_dates = tuple(sorted(cast("list[date]", daily["trade_date"].unique().to_list())))
    max_window = max(config.windows, default=config.main_window)
    first_target_index = all_dates.index(target_dates[0])
    moneyflow_start_date = all_dates[max(0, first_target_index - config.main_window + 1)]
    batch_inputs = IndustryPanelBatchInputs.prepare(
        cat_ts,
        cat_lx,
        config,
        target_dates=target_dates,
        moneyflow_start_date=moneyflow_start_date,
        end_date=target_dates[-1],
    )
    market_panels = _market_panel_batch(daily, config, target_dates, cat_ts)
    for target_date in target_dates:
        trade_dates = tuple(value for value in all_dates if value <= target_date)[-max_window:]
        panel = build_industry_panel_from_daily(
            config,
            as_of_date=target_date,
            trade_dates=trade_dates,
            industry_daily=daily,
            cat_ts=cat_ts,
            cat_lx=cat_lx,
            batch_inputs=batch_inputs,
            market_panel=market_panels.get(target_date),
        )
        if not panel.is_empty():
            panels.append(panel)

    result = (
        pl.concat(panels, how="vertical_relaxed")
        if panels
        else pl.DataFrame(schema=BASE_PANEL_SCHEMA)
    )
    if not result.is_empty():
        store.save_industry_panel_daily(result, overwrite=overwrite)
    return result


def _add_tcr_percentile(frame: pl.DataFrame) -> pl.DataFrame:
    """按行业历史序列补齐截至当日的 TCR 分位。"""
    if frame.is_empty() or "tcr" not in frame.columns:
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("tcr_percentile"))
    rows: list[dict[str, object]] = []
    for _code, group in frame.sort(["industry_code", "trade_date"]).group_by(
        "industry_code", maintain_order=True
    ):
        history: list[object] = []
        for row in group.to_dicts():
            current = row.get("tcr")
            history.append(current)
            row["tcr_percentile"] = historical_percentile(history, _as_float(current))
            rows.append(row)
    return pl.DataFrame(rows, schema={**frame.schema, "tcr_percentile": pl.Float64})


def _incremental_start(
    store: FeatureStore,
    mart_name: str,
    *,
    requested_start: date | None,
    end_date: date | None,
    overwrite: bool,
    date_column: str = "trade_date",
) -> date | None:
    if overwrite:
        return requested_start
    existing = store.get_domain_mart(
        mart_name,
        date_column=date_column,
        columns=[date_column],
    )
    if existing.is_empty() or date_column not in existing.columns:
        return requested_start
    latest = existing[date_column].drop_nulls().max()
    if not isinstance(latest, date) or (end_date is not None and latest > end_date):
        return requested_start
    if requested_start is None or requested_start <= latest:
        return latest
    return requested_start


def _with_lookback(start_date: date | None, config: IndustryStructureConfig) -> date | None:
    if start_date is None:
        return None
    return start_date - timedelta(days=max(config.windows, default=config.main_window) * 4)


def _target_dates(
    daily: pl.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, ...]:
    values = [value for value in daily["trade_date"].unique().to_list() if isinstance(value, date)]
    return tuple(
        sorted(
            value
            for value in values
            if (start_date is None or value >= start_date)
            and (end_date is None or value <= end_date)
        )
    )


def _load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    start_date: date | None,
    end_date: date | None,
    columns: list[str],
    dataset_cache: DatasetFrameCache | None,
) -> pl.DataFrame:
    try:
        if dataset_cache is not None:
            return dataset_cache.load(
                catalog,
                dataset,
                start_date=start_date,
                end_date=end_date,
                columns=columns,
            )
        return catalog.load_dataset(
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )
    except Exception:
        return pl.DataFrame()


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(cast("Any", value))
    except (TypeError, ValueError):
        return None
    return number


__all__ = [
    "INDUSTRY_DAILY_MART_NAME",
    "INDUSTRY_PANEL_DAILY_MART_NAME",
    "build_industry_daily_frame",
    "build_industry_daily_mart",
    "build_industry_panel_daily_mart",
    "empty_industry_daily",
]
