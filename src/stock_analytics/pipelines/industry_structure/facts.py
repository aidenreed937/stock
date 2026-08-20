"""行业结构分析事实层采集。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.fact_watermarks import _latest_dataset_date
from stock_analytics.pipelines.industry_structure.fact_watermarks import (
    collect_dataset_rows as _dataset_rows,
)
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig

FACT_SCHEMA: dict[str, Any] = {
    "fact_id": pl.Utf8,
    "category": pl.Utf8,
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

__all__ = ["_latest_dataset_date", "collect_facts", "empty_facts", "resolve_trade_window"]


def empty_facts() -> pl.DataFrame:
    """返回稳定 schema 的空事实表。"""
    return pl.DataFrame(schema=FACT_SCHEMA)


def resolve_trade_window(
    config: IndustryStructureConfig,
    target_date: date | None = None,
    *,
    storage_dir: Path | str | None = None,
    catalog: MarketDataCatalog | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> tuple[date, tuple[date, ...]]:
    """解析最近 N 个已落盘申万行业交易日窗口。"""
    max_window = max(config.windows, default=config.main_window)
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
        dates = active_catalog.latest_trade_dates(dataset="sw_daily", n=max_window)
    else:
        start_date = (target_date or date.today()) - timedelta(days=max_window * 4)
        frame = active_catalog.load_dataset(
            "sw_daily",
            start_date=start_date,
            end_date=target_date,
        )
        dates = (
            _date_values(frame["trade_date"].unique().to_list())
            if "trade_date" in frame.columns
            else []
        )
    trade_dates = tuple(
        sorted({value for value in dates if target_date is None or value <= target_date})
    )
    if not trade_dates:
        raise ValueError("无法解析行业结构交易日窗口: sw_daily 无可用交易日")
    as_of_date = target_date or trade_dates[-1]
    window_dates = tuple(value for value in trade_dates if value <= as_of_date)[-max_window:]
    return as_of_date, window_dates


def collect_facts(
    config: IndustryStructureConfig,
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    industry_panel: pl.DataFrame,
    storage_dir: Path | str | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    """采集窗口、水位和行业面板摘要事实。"""
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
    rows.extend(_panel_summary_rows(as_of_date, industry_panel))
    return pl.DataFrame(rows, schema=FACT_SCHEMA) if rows else empty_facts()


def _window_rows(
    config: IndustryStructureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in config.windows:
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
                    "data_source": "tushare",
                    "dataset": "sw_daily",
                    "as_of_date": as_of_date,
                    "window": window,
                    "metric_id": f"window_{window}d",
                    "source": "DataCatalog.latest_trade_dates",
                    "status": status,
                    "note": "最近已落盘申万行业交易日窗口",
                },
                value_text=value_text,
                sample_size=len(window_dates),
            )
        )
    return rows


def _panel_summary_rows(as_of_date: date, panel: pl.DataFrame) -> list[dict[str, Any]]:
    if panel.is_empty():
        return [
            _fact_row(
                {
                    "fact_id": "panel.industry_count",
                    "category": "panel_summary",
                    "data_source": "derived",
                    "dataset": "industry_panel",
                    "as_of_date": as_of_date,
                    "window": 0,
                    "metric_id": "industry_count",
                    "source": "industry_structure.panel",
                    "status": "insufficient",
                    "note": "行业面板无可用记录",
                },
                value_float=0.0,
                sample_size=0,
            )
        ]
    rows = [
        _summary_metric_row(
            as_of_date,
            "industry_count",
            float(panel.height),
            sample_size=panel.height,
            note="行业面板记录数",
        ),
        _summary_metric_row(
            as_of_date,
            "scored_industry_count",
            float(panel.filter(pl.col("structure_score").is_not_null()).height)
            if "structure_score" in panel.columns
            else 0.0,
            sample_size=panel.height,
            note="可评分行业数",
        ),
    ]
    if "market_data_date" in panel.columns:
        rows.append(_panel_date_row(as_of_date, panel, "market_data_date", "行业行情实际计算日期"))
    if "valuation_date" in panel.columns:
        rows.append(_panel_date_row(as_of_date, panel, "valuation_date", "行业估值实际使用日期"))
    if "fundamental_date" in panel.columns:
        rows.append(
            _panel_date_row(
                as_of_date,
                panel,
                "fundamental_date",
                "行业财报实际使用日期，季频慢变量，只代表中期底座",
            )
        )
    for metric_id, note in (
        ("forecast_date", "业绩预告快速基本面实际使用公告日期"),
        ("express_date", "业绩快报快速基本面实际使用公告日期"),
        ("report_rc_date", "研报盈利预测快速基本面实际使用日期"),
    ):
        if metric_id in panel.columns:
            rows.append(_panel_date_row(as_of_date, panel, metric_id, note))
    for metric_id, note in (
        ("forecast_sample_size", "业绩预告快速基本面覆盖股票数"),
        ("express_sample_size", "业绩快报快速基本面覆盖股票数"),
        ("report_rc_sample_size", "研报盈利预测修订样本数"),
    ):
        if metric_id in panel.columns:
            rows.append(_panel_sample_row(as_of_date, panel, metric_id, note))
    return rows


def _panel_date_row(
    as_of_date: date,
    panel: pl.DataFrame,
    metric_id: str,
    note: str,
) -> dict[str, Any]:
    dates = _date_values(panel[metric_id].drop_nulls().unique().to_list())
    latest = max(dates) if dates else None
    lag_text = f"; 距基准日 {max((as_of_date - latest).days, 0)} 天" if latest else ""
    return _fact_row(
        {
            "fact_id": f"panel.{metric_id}",
            "category": "panel_summary",
            "data_source": "derived",
            "dataset": "industry_panel",
            "as_of_date": as_of_date,
            "window": 0,
            "metric_id": metric_id,
            "source": "industry_structure.panel",
            "status": "ok" if dates else "insufficient",
            "note": f"{note}{lag_text}",
        },
        value_text=",".join(value.isoformat() for value in sorted(dates)),
        sample_size=len(dates),
    )


def _panel_sample_row(
    as_of_date: date,
    panel: pl.DataFrame,
    metric_id: str,
    note: str,
) -> dict[str, Any]:
    values = panel[metric_id].drop_nulls().to_list()
    total = sum(int(value) for value in values if value is not None)
    status = "ok" if total > 0 else "insufficient"
    return _fact_row(
        {
            "fact_id": f"panel.{metric_id}",
            "category": "panel_summary",
            "data_source": "derived",
            "dataset": "industry_panel",
            "as_of_date": as_of_date,
            "window": 0,
            "metric_id": metric_id,
            "source": "industry_structure.panel",
            "status": status,
            "note": note,
        },
        value_float=float(total),
        sample_size=len(values),
    )


def _summary_metric_row(
    as_of_date: date,
    metric_id: str,
    value: float,
    *,
    sample_size: int,
    note: str,
) -> dict[str, Any]:
    return _fact_row(
        {
            "fact_id": f"panel.{metric_id}",
            "category": "panel_summary",
            "data_source": "derived",
            "dataset": "industry_panel",
            "as_of_date": as_of_date,
            "window": 0,
            "metric_id": metric_id,
            "source": "industry_structure.panel",
            "status": "ok",
            "note": note,
        },
        value_float=value,
        sample_size=sample_size,
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
        return date(int(text[:4]), int(text[4:6]), 1)
    return date.fromisoformat(text[:10])
