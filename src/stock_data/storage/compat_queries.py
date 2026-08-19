"""去重主键与 DuckDB 查询条件兼容规则。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.core.task_registry import resolve_task


def _resolve_dedup_keys(
    dataset_name: str,
    source: str | None,
    data_source: str | None,
    merged: pl.DataFrame,
    bar_datasets: tuple[str, ...] | frozenset[str] | set[str] = (
        "stock_daily_bar",
        "index_daily_bar",
    ),
) -> list[str]:
    if dataset_name in bar_datasets:
        return [column for column in ("market", "symbol", "trade_date") if column in merged.columns]

    provider = (source or data_source or "tushare").lower()
    meta_keys: list[str] = []
    try:
        task = resolve_task(provider, dataset_name)
        api_name = task.api_name
        meta: Any = None
        if provider == "tushare":
            from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

            meta = TUSHARE_API_REGISTRY.get(api_name)
        elif provider == "lixinger":
            from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

            meta = LIXINGER_API_REGISTRY.get(api_name)
        elif provider == "yfinance":
            from stock_data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

            meta = YFINANCE_API_REGISTRY.get(api_name)
        if meta and getattr(meta, "primary_keys", None):
            meta_keys = list(meta.primary_keys)
    except Exception:
        pass

    if meta_keys:
        mapped_keys: list[str] = []
        for key in meta_keys:
            if key in {
                "ts_code",
                "stockCode",
                "code",
                "index_code",
                "con_code",
                "index_id",
                "industry_id",
            }:
                for candidate in (
                    key,
                    "symbol",
                    "ts_code",
                    "stockCode",
                    "code",
                    "index_id",
                    "industry_id",
                    "index_code",
                ):
                    if candidate in merged.columns:
                        mapped_keys.append(candidate)
                        break
            elif key in {"Date", "trade_date", "date", "suspend_date"}:
                for candidate in (key, "trade_date", "date", "Date", "suspend_date"):
                    if candidate in merged.columns:
                        mapped_keys.append(candidate)
                        break
            elif key in {"asOfDate", "as_of_date", "end_date", "report_date"}:
                for candidate in (key, "as_of_date", "asOfDate", "end_date", "report_date"):
                    if candidate in merged.columns:
                        mapped_keys.append(candidate)
                        break
            elif key in merged.columns:
                mapped_keys.append(key)

        if mapped_keys:
            if "market" in merged.columns and "market" not in mapped_keys:
                mapped_keys = ["market", *mapped_keys]
            return list(dict.fromkeys(mapped_keys))

    entity_cols = [
        column
        for column in (
            "symbol",
            "index_code",
            "con_code",
            "stockCode",
            "ts_code",
            "code",
            "index_id",
            "industry_id",
            "exchange_id",
        )
        if column in merged.columns
    ]
    period_cols = [
        column
        for column in (
            "trade_date",
            "date",
            "month",
            "quarter",
            "end_date",
            "in_date",
            "out_date",
            "suspend_date",
        )
        if column in merged.columns
    ]
    dedup_cols = (["market"] if "market" in merged.columns else []) + entity_cols + period_cols
    return list(dict.fromkeys(dedup_cols)) if (entity_cols or period_cols) else []


def _build_dataset_query_clause(
    matched_files: list[str],
    symbol: str | None = None,
    start_date: object | None = None,
    end_date: object | None = None,
) -> tuple[list[str], str]:
    conditions: list[str] = []
    order_cols: list[str] = []
    if not matched_files:
        return conditions, ""
    try:
        first_schema = pl.read_parquet_schema(matched_files[0])
        if symbol and "symbol" in first_schema:
            conditions.append(f"symbol = '{symbol}'")
        elif symbol and "ts_code" in first_schema:
            conditions.append(f"ts_code = '{symbol}'")
        if start_date:
            sd_str = (
                f"{start_date:%Y-%m-%d}" if hasattr(start_date, "strftime") else str(start_date)
            )
            if "trade_date" in first_schema:
                conditions.append(f"trade_date >= '{sd_str}'")
            elif "date" in first_schema:
                conditions.append(f"date >= '{sd_str}'")
        if end_date:
            ed_str = f"{end_date:%Y-%m-%d}" if hasattr(end_date, "strftime") else str(end_date)
            if "trade_date" in first_schema:
                conditions.append(f"trade_date <= '{ed_str}'")
            elif "date" in first_schema:
                conditions.append(f"date <= '{ed_str}'")
        for column in ("trade_date", "date", "month", "quarter"):
            if column in first_schema:
                order_cols.append(f"{column} ASC")
                break
        if "symbol" in first_schema:
            order_cols.append("symbol ASC")
    except Exception:
        pass
    return conditions, f" ORDER BY {', '.join(order_cols)}" if order_cols else ""


class QueryCompatMixin:
    """对外提供数据集去重与 SQL 条件构造兼容方法。"""

    @staticmethod
    def resolve_dedup_keys(
        dataset_name: str,
        source: str | None,
        data_source: str | None,
        merged: pl.DataFrame,
        bar_datasets: tuple[str, ...] | frozenset[str] | set[str] = (
            "stock_daily_bar",
            "index_daily_bar",
        ),
    ) -> list[str]:
        return _resolve_dedup_keys(dataset_name, source, data_source, merged, bar_datasets)

    @staticmethod
    def build_dataset_query_clause(
        matched_files: list[str],
        symbol: str | None = None,
        start_date: object | None = None,
        end_date: object | None = None,
    ) -> tuple[list[str], str]:
        return _build_dataset_query_clause(matched_files, symbol, start_date, end_date)
