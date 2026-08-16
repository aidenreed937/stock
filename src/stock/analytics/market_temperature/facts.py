"""市场温度计事实层采集。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock.analytics.market_temperature.derived import collect_derived_metric_rows
from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.engine import MetricEngine
from stock.data.catalog import DataCatalog

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from stock.analytics.market_temperature.config import (
        DatasetConfig,
        DimensionConfig,
        MarketTemperatureConfig,
        MetricInputConfig,
    )

FACT_SCHEMA: dict[str, Any] = {
    "fact_id": pl.Utf8,
    "category": pl.Utf8,
    "dimension": pl.Utf8,
    "data_source": pl.Utf8,
    "dataset": pl.Utf8,
    "as_of_date": pl.Date,
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


def empty_facts() -> pl.DataFrame:
    """返回稳定 schema 的空事实表。"""
    return pl.DataFrame(schema=FACT_SCHEMA)


def resolve_trade_window(
    config: MarketTemperatureConfig,
    target_date: date | None = None,
    *,
    storage_dir: Path | str | None = None,
) -> tuple[date, tuple[date, ...]]:
    """解析最近 N 个已落盘交易日窗口。"""
    max_window = max((config.main_window, *config.short_windows), default=config.main_window)
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    if target_date is None:
        dates = catalog.latest_trade_dates(dataset="stock_daily_bar", n=max_window)
    else:
        start_date = target_date - timedelta(days=max_window * 4)
        frame = catalog.load_dataset(
            "stock_daily_bar",
            start_date=start_date,
            end_date=target_date,
        )
        if "trade_date" in frame.columns:
            dates = _date_values(frame["trade_date"].unique().to_list())
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


def collect_facts(
    config: MarketTemperatureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
    collect_metric_values: bool | None = None,
) -> pl.DataFrame:
    """采集窗口、数据水位和可选指标事实。"""
    rows: list[dict[str, Any]] = []
    rows.extend(_window_rows(config, as_of_date, trade_dates))
    rows.extend(_dataset_rows(config.datasets, as_of_date, storage_dir=storage_dir))
    should_collect_metrics = (
        config.metric_values.enabled if collect_metric_values is None else collect_metric_values
    )
    if should_collect_metrics:
        rows.extend(
            _metric_rows(
                config.dimensions,
                as_of_date,
                storage_dir=storage_dir,
            )
        )
        rows.extend(
            collect_derived_metric_rows(
                as_of_date=as_of_date,
                trade_dates=trade_dates,
                storage_dir=storage_dir,
            )
        )
    return pl.DataFrame(rows, schema=FACT_SCHEMA) if rows else empty_facts()


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


def _dataset_rows(
    datasets: Iterable[DatasetConfig],
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    catalogs: dict[str, DataCatalog] = {}
    for item in datasets:
        catalog = catalogs.setdefault(
            item.data_source,
            DataCatalog(data_source=item.data_source, storage_dir=storage_dir),
        )
        status = "ok"
        latest_text = ""
        note = item.note
        sample_size: int | None = None
        try:
            latest = _latest_dataset_date(catalog, item)
            if latest is None:
                if item.static:
                    sample_size = _static_dataset_sample_size(catalog, item.dataset)
                    if sample_size > 0:
                        status = "ok"
                        latest_text = "static"
                        note = f"{note}; 静态表，无交易日期列".strip("; ")
                    else:
                        status = "missing" if item.required else "unavailable"
                        note = f"{note}; 静态表无可用记录".strip("; ")
                else:
                    status = "missing" if item.required else "unavailable"
                    note = f"{note}; 未找到最新日期".strip("; ")
            else:
                latest_text = latest.isoformat()
                if latest > as_of_date:
                    status = "future"
                elif item.required and latest < as_of_date - timedelta(days=item.max_lag_days):
                    status = "lagging"
        except Exception as exc:
            status = "error" if item.required else "unavailable"
            note = f"{note}; {type(exc).__name__}: {exc}".strip("; ")
        rows.append(
            _fact_row(
                {
                    "fact_id": f"watermark.{item.data_source}.{item.dataset}",
                    "category": "data_watermark",
                    "dimension": item.dimension,
                    "data_source": item.data_source,
                    "dataset": item.dataset,
                    "as_of_date": as_of_date,
                    "window": 0,
                    "metric_id": "latest_trade_date",
                    "source": "DataCatalog.get_latest_trade_date",
                    "status": status,
                    "note": note,
                },
                value_text=latest_text,
                sample_size=sample_size,
            )
        )
    return rows


def _static_dataset_sample_size(catalog: DataCatalog, dataset: str) -> int:
    try:
        return catalog.load_dataset(dataset).height
    except Exception:
        return 0


def _latest_dataset_date(catalog: DataCatalog, item: DatasetConfig) -> date | None:
    if not item.date_column:
        return catalog.get_latest_trade_date(item.dataset)
    frame = catalog.load_dataset(item.dataset)
    if frame.is_empty() or item.date_column not in frame.columns:
        return None
    dates = _date_values(frame[item.date_column].drop_nulls().to_list())
    return max(dates) if dates else None


def _metric_rows(
    dimensions: Iterable[DimensionConfig],
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    context = MetricContext(
        catalog=DataCatalog(data_source="tushare", storage_dir=storage_dir),
        target_date=as_of_date,
        start_date=as_of_date - timedelta(days=365 * 7),
        end_date=as_of_date,
    )
    engine = MetricEngine()
    for dimension in dimensions:
        for metric in dimension.metrics:
            if not metric.enabled or metric.source != "metric_engine":
                continue
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
            return _metric_fact(
                metric,
                dimension,
                as_of_date,
                "insufficient",
                {"note": "指标无可用输出"},
            )
        latest_date = _latest_metric_date(frame, as_of_date)
        if latest_date is None:
            return _metric_fact(
                metric,
                dimension,
                as_of_date,
                "insufficient",
                {"note": "指标无最新日期"},
            )
        latest_frame = frame.filter(pl.col("trade_date") == latest_date)
        if latest_frame.is_empty():
            return _metric_fact(
                metric,
                dimension,
                as_of_date,
                "insufficient",
                {"note": "指标无最新日期"},
            )
        value = _aggregate_metric(latest_frame, metric.metric_id, metric.aggregation)
        if value is None:
            return _metric_fact(
                metric,
                dimension,
                as_of_date,
                "insufficient",
                {"note": "指标值为空"},
            )
        return _metric_fact(
            metric,
            dimension,
            as_of_date,
            "ok",
            {
                "value_float": value,
                "sample_size": latest_frame.height,
                "note": f"metric_date={latest_date.isoformat()}; aggregation={metric.aggregation}",
            },
        )
    except Exception as exc:
        return _metric_fact(
            metric,
            dimension,
            as_of_date,
            "error",
            {"note": f"{type(exc).__name__}: {exc}"},
        )


def _latest_metric_date(frame: pl.DataFrame, as_of_date: date) -> date | None:
    if "trade_date" not in frame.columns:
        return None
    metric_columns = [column for column in frame.columns if column != "trade_date"]
    if metric_columns:
        frame = frame.filter(
            pl.any_horizontal([pl.col(column).is_not_null() for column in metric_columns])
        )
    latest_dates = frame.filter(pl.col("trade_date") <= as_of_date)["trade_date"]
    dates = _date_values(latest_dates.drop_nulls().unique().to_list())
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
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = values or {}
    return _fact_row(
        {
            "fact_id": f"metric.{dimension}.{metric.metric_id}",
            "category": "metric_value",
            "dimension": dimension,
            "data_source": "metric_engine",
            "dataset": "",
            "as_of_date": as_of_date,
            "window": 0,
            "metric_id": metric.metric_id,
            "source": "MetricEngine.compute",
            "status": status,
            "note": str(extra.get("note", "")),
        },
        value_float=extra.get("value_float"),
        unit="raw",
        sample_size=extra.get("sample_size"),
    )


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


def _date_values(values: Iterable[object]) -> list[date]:
    dates: list[date] = []
    for value in values:
        parsed = _parse_date_value(value)
        if parsed is not None:
            dates.append(parsed)
    return dates


def _parse_date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    if len(text) >= 6 and text[:6].isdigit():
        year = int(text[:4])
        month = int(text[4:6])
        return date(year, month, 1)
    return date.fromisoformat(text[:10])
