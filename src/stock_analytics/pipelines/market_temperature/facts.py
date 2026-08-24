"""市场温度计事实层采集。"""

from __future__ import annotations  # noqa: I001

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.fact_watermarks import (
    _latest_dataset_date,
    collect_dataset_rows as _dataset_rows,
)
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.facts_mart import (
    date_values,
    parse_date_value as _parse_date_value,  # noqa: F401
)
from stock_analytics.pipelines.market_temperature.optional_facts import collect_optional_fact_rows
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import MarketTemperatureConfig

FACT_SCHEMA: dict[str, Any] = {
    "fact_id": pl.Utf8,
    "category": pl.Utf8,
    "dimension": pl.Utf8,
    "data_source": pl.Utf8,
    "dataset": pl.Utf8,
    "as_of_date": pl.Date,
    "metric_date": pl.Date,
    "window": pl.Int64,
    "metric_id": pl.Utf8,
    "value_float": pl.Float64,
    "value_text": pl.Utf8,
    "unit": pl.Utf8,
    "sample_size": pl.Int64,
    "source": pl.Utf8,
    "status": pl.Utf8,
    "note": pl.Utf8,
}

__all__ = [
    "_latest_dataset_date",
    "collect_facts",
    "empty_facts",
    "resolve_external_cutoff_date",
    "resolve_trade_window",
]


def empty_facts() -> pl.DataFrame:
    """返回稳定 schema 的空事实表。"""
    return pl.DataFrame(schema=FACT_SCHEMA)


def resolve_trade_window(
    config: MarketTemperatureConfig,
    target_date: date | None = None,
    *,
    storage_dir: Path | str | None = None,
    catalog: MarketDataCatalog | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> tuple[date, tuple[date, ...]]:
    """解析最近 N 个已落盘交易日窗口。"""
    max_window = max((config.main_window, *config.short_windows), default=config.main_window)
    active_catalog: MarketDataCatalog
    if catalog is not None:
        active_catalog = catalog
    else:
        from stock_data.catalog import DataCatalog

        active_catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    if dataset_cache is not None:
        from stock_analytics.pipelines.market_temperature.cache import CachedCatalog

        active_catalog = CachedCatalog(active_catalog, dataset_cache)
    if target_date is None and hasattr(active_catalog, "latest_trade_dates"):
        dates = active_catalog.latest_trade_dates(dataset="stock_daily_bar", n=max_window)
    else:
        start_date = (target_date or date.today()) - timedelta(days=max_window * 4)
        frame = active_catalog.load_dataset(
            "stock_daily_bar",
            start_date=start_date,
            end_date=target_date,
        )
        if "trade_date" in frame.columns:
            dates = date_values(frame["trade_date"].unique().to_list())
        else:
            dates = []

    trade_dates = tuple(
        sorted({value for value in dates if target_date is None or value <= target_date})
    )
    if not trade_dates:
        raise ValueError("无法解析市场温度计交易日窗口: stock_daily_bar 无可用交易日")
    as_of_date = target_date or trade_dates[-1]
    window_dates = tuple(value for value in trade_dates if value <= as_of_date)[-max_window:]
    return as_of_date, window_dates


def resolve_external_cutoff_date(
    as_of_date: date,
    trade_dates: tuple[date, ...],
) -> date:
    """返回外盘在该 A 股基准日可使用的最后一个交易日。"""
    return max(
        (value for value in trade_dates if value < as_of_date),
        default=as_of_date - timedelta(days=1),
    )


def collect_facts(
    config: MarketTemperatureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
    collect_metric_values: bool | None = None,
    market_daily: pl.DataFrame | None = None,
    dataset_cache: DatasetFrameCache | None = None,
    external_cutoff_date: date | None = None,
) -> pl.DataFrame:
    """采集窗口、数据水位和可选指标事实。"""
    rows: list[dict[str, Any]] = []
    rows.extend(_window_rows(config, as_of_date, trade_dates))
    rows.extend(
        _dataset_rows(
            config.datasets,
            as_of_date,
            storage_dir=storage_dir,
            dataset_cache=dataset_cache,
            fact_row=_fact_row,
        )
    )
    should_collect_metrics = (
        config.metric_values.enabled if collect_metric_values is None else collect_metric_values
    )
    if should_collect_metrics:
        del market_daily, dataset_cache, external_cutoff_date
        rows.extend(_load_materialized_metric_rows(config, as_of_date, storage_dir))
        rows.extend(collect_optional_fact_rows(config, as_of_date, storage_dir))
    return (
        pl.DataFrame(_normalize_metric_dates(rows), schema=FACT_SCHEMA) if rows else empty_facts()
    )


def _load_materialized_metric_rows(
    config: MarketTemperatureConfig,
    as_of_date: date,
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    """读取指定基准日的派生事实快照，不执行任何运行时重算。"""
    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    frame = store.get_market_temperature_derived_facts(as_of_date)
    rows = frame.to_dicts() if not frame.is_empty() else []
    existing = {
        (str(row.get("dimension")), str(row.get("metric_id")))
        for row in rows
        if row.get("category") == "metric_value"
    }
    if not rows:
        mart_note = "市场温度派生事实 Mart 缺失或不含该基准日"
    else:
        mart_note = "市场温度派生事实 Mart 未物化该指标"

    for dimension in config.dimensions:
        for metric in dimension.metrics:
            if not metric.enabled or metric.source not in {"metric_engine", "derived"}:
                continue
            key = (dimension.id, metric.metric_id)
            if key in existing:
                continue
            rows.append(
                _materialized_unavailable_row(
                    dimension.id,
                    metric.metric_id,
                    as_of_date,
                    mart_note,
                )
            )
            existing.add(key)

    for window in config.short_windows:
        metric_id = f"short_term_temperature_{window}d"
        if ("short_term", metric_id) not in existing:
            rows.append(
                _materialized_unavailable_row(
                    "short_term",
                    metric_id,
                    as_of_date,
                    mart_note,
                    window=window,
                )
            )
    return rows


def _materialized_unavailable_row(
    dimension: str,
    metric_id: str,
    as_of_date: date,
    note: str,
    *,
    window: int = 0,
) -> dict[str, Any]:
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "mart",
        "dataset": "market_temperature_derived_facts",
        "as_of_date": as_of_date,
        "metric_date": None,
        "window": window,
        "metric_id": metric_id,
        "value_float": None,
        "value_text": "",
        "unit": "temperature",
        "sample_size": 0,
        "source": "FeatureStore.market_temperature_derived_facts",
        "status": "unavailable",
        "note": note,
    }


def _normalize_metric_dates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为指标事实补齐统一的 metric_date 列，保留旧 note 兼容解析。"""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("category") == "metric_value":
            item["metric_date"] = _metric_date_from_row(item)
        else:
            item["metric_date"] = None
        normalized.append(item)
    return normalized


def _metric_date_from_row(row: dict[str, Any]) -> date | None:
    for key in ("metric_date", "latest_evaluation_date"):
        parsed = _parse_date_value(row.get(key))
        if parsed is not None:
            return parsed
    note = str(row.get("note") or "")
    for prefix in ("metric_date=", "latest_date=", "report_date="):
        marker = f"{prefix}"
        if marker in note:
            value = note.split(marker, 1)[1].split(";", 1)[0].strip()
            parsed = _parse_date_value(value)
            if parsed is not None:
                return parsed
    if "ann_window=" in note:
        value = note.split("ann_window=", 1)[1].split(";", 1)[0].split("..")[-1].strip()
        parsed = _parse_date_value(value)
        if parsed is not None:
            return parsed
    return None


def _window_rows(
    config: MarketTemperatureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in (config.main_window, *config.short_windows):
        window_dates = trade_dates[-window:]
        status = "ok" if len(window_dates) >= window else "insufficient"
        value_text = ""
        if window_dates:
            value_text = f"{window_dates[0].isoformat()}..{window_dates[-1].isoformat()}"
        rows.append(
            _fact_row(
                {
                    "fact_id": f"window_{window}d",
                    "category": "analysis_window",
                    "dimension": "meta",
                    "data_source": "tushare",
                    "dataset": "stock_daily_bar",
                    "as_of_date": as_of_date,
                    "window": window,
                    "metric_id": f"window_{window}d",
                    "source": "DataCatalog.latest_trade_dates",
                    "status": status,
                    "note": "最近已落盘交易日窗口",
                },
                value_text=value_text,
                sample_size=len(window_dates),
            )
        )
    return rows


def _fact_row(
    base: dict[str, Any],
    *,
    value_float: float | None = None,
    value_text: str = "",
    unit: str = "",
    sample_size: int | None = None,
) -> dict[str, Any]:
    return {
        "fact_id": base["fact_id"],
        "category": base["category"],
        "dimension": base["dimension"],
        "data_source": base["data_source"],
        "dataset": base["dataset"],
        "as_of_date": base["as_of_date"],
        "window": base["window"],
        "metric_id": base["metric_id"],
        "value_float": value_float,
        "value_text": value_text,
        "unit": unit,
        "sample_size": sample_size,
        "source": base["source"],
        "status": base["status"],
        "note": base["note"],
    }
