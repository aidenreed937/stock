"""市场温度计的可选短线与领域 Mart 观察事实。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.domain_mart_facts import (
    collect_domain_mart_observations,
)

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import MarketTemperatureConfig


def collect_optional_fact_rows(
    config: MarketTemperatureConfig,
    as_of_date: date,
    storage_dir: Path | str | None,
) -> list[dict[str, Any]]:
    """收集不参与六维主温度的短线与领域观察事实。"""
    rows = _short_term_rows(config.short_windows, as_of_date, storage_dir)
    if config.domain_mart_observations_enabled:
        rows.extend(
            collect_domain_mart_observations(as_of_date=as_of_date, storage_dir=storage_dir)
        )
    return rows


def _short_term_rows(
    windows: tuple[int, ...], as_of_date: date, storage_dir: Path | str | None
) -> list[dict[str, Any]]:
    """从 market_daily 宽表计算独立的短线温度附加事实。"""
    if not windows:
        return []
    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    frame = store.get_market_daily(end_date=as_of_date)
    if frame.is_empty() or "trade_date" not in frame.columns:
        return [
            _short_term_fact(window, as_of_date, None, 0, "market_daily 不可用")
            for window in windows
        ]

    rows: list[dict[str, Any]] = []
    for window in windows:
        sample = frame.filter(pl.col("trade_date") <= as_of_date).tail(window)
        if sample.height < window:
            rows.append(
                _short_term_fact(
                    window,
                    as_of_date,
                    None,
                    sample.height,
                    f"短线窗口需要 {window} 个交易日，实际 {sample.height} 个",
                )
            )
            continue

        component_values: list[float] = []
        for column in ("advance_ratio", "above_ma20_ratio", "above_ma60_ratio"):
            if column in sample.columns:
                value = sample[column].drop_nulls().mean()
                if value is not None:
                    component_values.append(float(cast("Any", value)) * 100.0)
        if "main_net_inflow_ratio" in sample.columns:
            value = sample["main_net_inflow_ratio"].drop_nulls().mean()
            if value is not None:
                component_values.append(50.0 + float(cast("Any", value)) * 1000.0)
        if not component_values:
            rows.append(
                _short_term_fact(window, as_of_date, None, sample.height, "短线指标列不可用")
            )
            continue
        temperature = min(100.0, max(0.0, sum(component_values) / len(component_values)))
        rows.append(
            _short_term_fact(
                window,
                as_of_date,
                round(temperature, 2),
                sample.height,
                "短线温度由 market_daily 可用技术/资金组件等权合成，不并入六维主温度",
            )
        )
    return rows


def _short_term_fact(
    window: int,
    as_of_date: date,
    value: float | None,
    sample_size: int,
    note: str,
) -> dict[str, Any]:
    return {
        "fact_id": f"short_term_temperature_{window}d",
        "category": "metric_value",
        "dimension": "short_term",
        "data_source": "mart",
        "dataset": "market_daily",
        "as_of_date": as_of_date,
        "window": window,
        "metric_id": f"short_term_temperature_{window}d",
        "value_float": value,
        "value_text": "" if value is None else f"{value:.2f}",
        "unit": "temperature",
        "sample_size": sample_size,
        "source": "FeatureStore.market_daily",
        "status": "ok" if value is not None else "insufficient",
        "note": note,
    }


__all__ = ["collect_optional_fact_rows"]
