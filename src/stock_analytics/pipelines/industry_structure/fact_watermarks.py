"""行业结构事实层数据水位检查。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.data_quality import is_dataset_lagging
from stock_analytics.pipelines.market_temperature.cache import CachedCatalog, DatasetFrameCache
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from stock_reporting.interpretation.industry_structure.config import DatasetConfig

FactRowFactory = Callable[..., dict[str, Any]]


def collect_dataset_rows(
    datasets: Iterable[DatasetConfig],
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
    dataset_cache: DatasetFrameCache | None,
    fact_row: FactRowFactory,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    catalogs: dict[str, MarketDataCatalog] = {}
    for item in datasets:
        if item.data_source not in catalogs:
            from stock_data.catalog import DataCatalog

            catalogs[item.data_source] = DataCatalog(
                data_source=item.data_source, storage_dir=storage_dir
            )
        catalog = catalogs[item.data_source]
        if dataset_cache is not None:
            catalog = CachedCatalog(catalog, dataset_cache)
        status = "ok"
        latest_text = ""
        note = item.note
        sample_size: int | None = None
        try:
            latest = _latest_dataset_date(catalog, item, as_of_date)
            if latest is None:
                if item.static:
                    sample_size = _static_dataset_sample_size(catalog, item.dataset)
                    if sample_size > 0:
                        status, latest_text = "ok", "static"
                        note = f"{note}; 静态字典表，无交易日期列".strip("; ")
                    else:
                        status = "missing" if item.required else "unavailable"
                        note = f"{note}; 静态字典表无可用记录".strip("; ")
                else:
                    status = "missing" if item.required else "unavailable"
                    note = f"{note}; 未找到最新日期".strip("; ")
            else:
                latest_text = latest.isoformat()
                if latest > as_of_date:
                    status = "future"
                elif is_dataset_lagging(
                    latest, as_of_date, required=item.required, max_lag_days=item.max_lag_days
                ):
                    status = "lagging"
        except Exception as exc:
            status = "error" if item.required else "unavailable"
            note = f"{note}; {type(exc).__name__}: {exc}".strip("; ")
        rows.append(
            fact_row(
                {
                    "fact_id": f"watermark.{item.data_source}.{item.dataset}",
                    "category": "data_watermark",
                    "data_source": item.data_source,
                    "dataset": item.dataset,
                    "as_of_date": as_of_date,
                    "window": 0,
                    "metric_id": "latest_trade_date",
                    "source": "DataCatalog.load_dataset(end_date=as_of_date)",
                    "status": status,
                    "note": note,
                },
                value_text=latest_text,
                sample_size=sample_size,
            )
        )
    return rows


def _static_dataset_sample_size(catalog: MarketDataCatalog, dataset: str) -> int:
    try:
        return catalog.load_dataset(dataset).height
    except Exception:
        return 0


def _load_dataset_date_frame(
    catalog: MarketDataCatalog,
    dataset: str,
    start_date: date,
    end_date: date,
    date_column: str,
) -> pl.DataFrame:
    try:
        return load_dataset_compat(
            catalog,
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=[date_column],
        )
    except Exception:
        return pl.DataFrame()


def _latest_dataset_date(
    catalog: MarketDataCatalog,
    item: DatasetConfig,
    as_of_date: date,
) -> date | None:
    date_column = item.date_column or "trade_date"
    if date_column == "trade_date" and hasattr(catalog, "latest_trade_dates"):
        latest_dates = catalog.latest_trade_dates(item.dataset, n=1)
        if latest_dates and latest_dates[0] <= as_of_date:
            return latest_dates[0]
    lookback_days = max(item.max_lag_days * 2, 90 if item.cadence in ("event", "quarterly") else 14)
    frame = _load_dataset_date_frame(
        catalog,
        item.dataset,
        as_of_date - timedelta(days=lookback_days),
        as_of_date,
        date_column,
    )
    if frame.is_empty() or date_column not in frame.columns:
        return None
    dates = [
        value
        for value in _date_values(frame[date_column].drop_nulls().to_list())
        if value <= as_of_date
    ]
    return max(dates) if dates else None


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
        return date(int(text[:4]), int(text[4:6]), 1)
    return date.fromisoformat(text[:10])
