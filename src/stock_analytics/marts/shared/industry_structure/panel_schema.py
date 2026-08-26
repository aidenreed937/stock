"""行业结构基础面板 Schema 与选择工具。"""

from __future__ import annotations

from typing import Any

import polars as pl

BASE_PANEL_SCHEMA: dict[str, Any] = {
    "as_of_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "market_data_date": pl.Date,
    "valuation_date": pl.Date,
    "fundamental_date": pl.Date,
    "return_5d": pl.Float64,
    "return_10d": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "return_120d": pl.Float64,
    "relative_return_20d": pl.Float64,
    "ma_bias_20d": pl.Float64,
    "amount_yi": pl.Float64,
    "tcr": pl.Float64,
    "tcr_percentile": pl.Float64,
    "moneyflow_date": pl.Date,
    "moneyflow_sample_size": pl.Int64,
    "moneyflow_stock_count": pl.Int64,
    "money_net_inflow_yi_20d": pl.Float64,
    "money_net_inflow_share_20d": pl.Float64,
    "large_money_net_inflow_share_20d": pl.Float64,
    "money_net_inflow_share_5d": pl.Float64,
    "pe_ttm": pl.Float64,
    "pb": pl.Float64,
    "dividend_yield": pl.Float64,
    "pe_percentile_5y": pl.Float64,
    "pb_percentile_5y": pl.Float64,
    "pbroe_residual": pl.Float64,
    "pbroe_undervalued": pl.Boolean,
    "revenue_growth_ttm": pl.Float64,
    "profit_growth_ttm": pl.Float64,
    "roe_ttm": pl.Float64,
    "revenue_growth_percentile": pl.Float64,
    "profit_growth_percentile": pl.Float64,
    "roe_percentile": pl.Float64,
    "forecast_date": pl.Date,
    "forecast_sample_size": pl.Int64,
    "forecast_positive_share": pl.Float64,
    "forecast_p_change_mid_median": pl.Float64,
    "express_date": pl.Date,
    "express_sample_size": pl.Int64,
    "express_profit_growth_median": pl.Float64,
    "express_roe_median": pl.Float64,
    "report_rc_date": pl.Date,
    "report_rc_sample_size": pl.Int64,
    "report_rc_revision_ratio": pl.Float64,
    "report_rc_up_count": pl.Int64,
    "report_rc_down_count": pl.Int64,
}


def empty_industry_panel() -> pl.DataFrame:
    """返回稳定 schema 的空行业面板。"""
    return pl.DataFrame(schema=BASE_PANEL_SCHEMA)


def select_base_panel_columns(panel: pl.DataFrame) -> pl.DataFrame:
    """按基础面板契约补齐并投影列。"""
    columns = []
    for column, dtype in BASE_PANEL_SCHEMA.items():
        if column in panel.columns:
            columns.append(pl.col(column).cast(dtype, strict=False).alias(column))
        else:
            columns.append(pl.lit(None, dtype=dtype).alias(column))
    return panel.select(columns)


__all__ = ["BASE_PANEL_SCHEMA", "empty_industry_panel", "select_base_panel_columns"]
