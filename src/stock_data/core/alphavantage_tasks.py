"""Alpha Vantage 项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MakeTaskSpec = Callable[..., Any]


def build_alphavantage_tasks(make_spec: MakeTaskSpec) -> dict[tuple[str, str], Any]:
    """生成 Alpha Vantage 需要项目短任务名或显式调度契约的任务。"""
    return {
        ("alphavantage", "stock_daily_bar"): make_spec(
            "stock_daily_bar",
            "alphavantage",
            "TIME_SERIES_DAILY",
            "stock_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=True,
            max_increment_days=90,
        ),
        ("alphavantage", "fx_daily"): make_spec(
            "fx_daily",
            "alphavantage",
            "FX_DAILY",
            "macro_indicators",
            "macro",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("alphavantage", "company_overview"): make_spec(
            "company_overview",
            "alphavantage",
            "OVERVIEW",
            "company_overview",
            "generic",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            frequency="static",
            primary_keys=("symbol",),
            date_columns=("as_of_date", "latest_quarter"),
            required_columns=("symbol",),
            sync_policy="manual_snapshot",
        ),
        ("alphavantage", "earnings"): make_spec(
            "earnings",
            "alphavantage",
            "EARNINGS",
            "earnings",
            "generic",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            frequency="quarterly",
            primary_keys=("symbol", "report_type", "fiscal_date_ending"),
            date_columns=("fiscal_date_ending", "reported_date"),
            required_columns=("symbol", "report_type", "fiscal_date_ending"),
        ),
        ("alphavantage", "financials"): make_spec(
            "financials",
            "alphavantage",
            "INCOME_STATEMENT",
            "financials",
            "generic",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            frequency="quarterly",
            primary_keys=("symbol", "report_type", "fiscal_date_ending"),
            date_columns=("fiscal_date_ending", "reported_date"),
            required_columns=("symbol", "report_type", "fiscal_date_ending"),
        ),
        ("alphavantage", "balance_sheet"): make_spec(
            "balance_sheet",
            "alphavantage",
            "BALANCE_SHEET",
            "balance_sheet",
            "generic",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            frequency="quarterly",
            primary_keys=("symbol", "report_type", "fiscal_date_ending"),
            date_columns=("fiscal_date_ending", "reported_date"),
            required_columns=("symbol", "report_type", "fiscal_date_ending"),
        ),
        ("alphavantage", "cashflow"): make_spec(
            "cashflow",
            "alphavantage",
            "CASH_FLOW",
            "cashflow",
            "generic",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            frequency="quarterly",
            primary_keys=("symbol", "report_type", "fiscal_date_ending"),
            date_columns=("fiscal_date_ending", "reported_date"),
            required_columns=("symbol", "report_type", "fiscal_date_ending"),
        ),
    }


__all__ = ["build_alphavantage_tasks"]
