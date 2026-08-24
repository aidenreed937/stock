"""市场温度计派生事实编排门面。

具体事实计算按业务主题分布在 ``derived_fundamental``、
``derived_sentiment`` 与 ``derived_macro``；本模块保留历史导入路径，
并只负责跨主题编排。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.market_temperature.amount_concentration import (  # noqa: F401
    amount_top_5pct_daily_frame as _amount_top_5pct_daily_frame,
)  # noqa: F401
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.pipelines.market_temperature.derived_external import (  # noqa: F401
    _external_environment_row,
    _external_pressure_rows,
    _fred_symbol_frame,
    _fred_yoy_frame,
    _return_frame,
    _return_percentile_metric_row,
)
from stock_analytics.pipelines.market_temperature.derived_fundamental import (  # noqa: F401
    _financial_statement_rows,
    _forecast_rows,
    _fundamental_rows,
    _report_revision_rows,
)  # noqa: F401
from stock_analytics.pipelines.market_temperature.derived_helpers import (  # noqa: F401
    _historical_median_temperature,
    _load_dataset,
    _metric_row,
    _percentile_metric_row,
    _percentile_temperature,
    _with_month_date,
    _with_social_finance_yoy,
)  # noqa: F401
from stock_analytics.pipelines.market_temperature.derived_macro import (  # noqa: F401
    _external_macro_rows,
    _macro_liquidity_rows,
    _us_macro_background_rows,
)  # noqa: F401
from stock_analytics.pipelines.market_temperature.derived_sentiment import (  # noqa: F401
    _investor_account_frame,
    _investor_account_rows,
    _limit_event_daily_frame,
    _limit_event_rows,
    _option_rows,
    _sentiment_rows,
    collect_amount_top_5pct_share_rows,
)  # noqa: F401

if TYPE_CHECKING:
    from datetime import date


def collect_derived_metric_rows(
    *,
    as_of_date: date,
    trade_dates: tuple[date, ...],
    storage_dir: Path | str | None = None,
    dataset_cache: DatasetFrameCache | None = None,
    external_cutoff_date: date | None = None,
    market_daily: pl.DataFrame | None = None,
    market_daily_option_source_valid: bool | None = None,
    amount_top_5pct_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """采集不在 MetricEngine 内的基本面、情绪与宏观温度事实。"""
    rows = _fundamental_rows(as_of_date, trade_dates, storage_dir, dataset_cache)
    rows.extend(
        _sentiment_rows(
            as_of_date,
            storage_dir,
            dataset_cache,
            market_daily=market_daily,
            market_daily_option_source_valid=market_daily_option_source_valid,
            amount_top_5pct_row=amount_top_5pct_row,
        )
    )
    rows.extend(
        _macro_liquidity_rows(
            as_of_date,
            storage_dir,
            dataset_cache,
            external_cutoff_date=external_cutoff_date,
        )
    )
    return rows


__all__ = ["collect_amount_top_5pct_share_rows", "collect_derived_metric_rows"]
