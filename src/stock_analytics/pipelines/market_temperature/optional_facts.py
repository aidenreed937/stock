"""市场温度计的可选短线与领域 Mart 观察事实。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    """收集不参与六维主温度的领域 Mart 观察事实。"""
    rows: list[dict[str, Any]] = []
    if config.domain_mart_observations_enabled:
        rows.extend(
            collect_domain_mart_observations(as_of_date=as_of_date, storage_dir=storage_dir)
        )
    return rows


__all__ = ["collect_optional_fact_rows"]
