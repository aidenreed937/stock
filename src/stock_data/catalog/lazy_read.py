"""DataCatalog 标准 Parquet 的惰性读取辅助逻辑。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_core.exceptions import DataValidationError, StorageError
from stock_core.utils.logger import logger
from stock_data.governance.quality.margin_coverage import filter_complete_margin_dates
from stock_data.storage.read_compat import (
    normalize_read_frame,
    requires_read_normalization,
    validate_schema_version,
)

_LAZY_UNSAFE_DATASETS = frozenset(
    {
        "balance_sheet",
        "cashflow",
        "cn_cpi",
        "cn_gdp",
        "cn_m",
        "cn_ppi",
        "cn_pmi",
        "express",
        "financials",
        "hk_hold",
        "index_valuation",
        "interest_rates",
        "margin",
        "moneyflow_hsgt",
        "national_debt",
        "sf_month",
        "shibor",
        "shibor_lpr",
        "stk_account",
        "sw_daily",
    }
)
_IDENTITY_ALIASES = ("ts_code", "stockCode", "code")
_DATE_ALIASES = ("date",)


def read_columns(
    columns: Sequence[str],
    date_candidates: Sequence[str],
    dataset: str,
) -> set[str]:
    """返回读取和兼容过滤所需的内部列集合。"""
    wanted = set(columns)
    wanted.update(
        {
            "symbol",
            "ts_code",
            "stockCode",
            "code",
            "trade_date",
            "ann_date",
            "date",
            "report_date",
            "end_date",
            "publish_date",
            "schema_version",
            "market",
            "adjustment",
            "exchange",
            "exchange_id",
        }
    )
    wanted.update(date_candidates)
    if dataset == "index_valuation":
        wanted.add("total_assets")
    return wanted


def should_use_lazy_read(
    files: Sequence[Path],
    dataset: str,
    *,
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
    columns: Sequence[str] | None,
) -> bool:
    """只为标准 schema、受限读取选择 Lazy 路径。"""
    if not files or dataset in _LAZY_UNSAFE_DATASETS:
        return False
    if columns is None and start_date is None and end_date is None and not symbols:
        return False
    return all(not requires_read_normalization(path, dataset) for path in files)


def read_dataset_files_lazy(
    files: Sequence[Path],
    dataset: str,
    data_source: str,
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
    columns: Sequence[str] | None,
    *,
    date_candidates: Sequence[str],
) -> pl.DataFrame:
    """读取标准 Parquet，并下推安全的日期、标的和列过滤。"""
    schemas = [pl.read_parquet_schema(path) for path in files]
    wanted = read_columns(columns, date_candidates, dataset) if columns is not None else None
    common_date = next(
        (
            column
            for column in date_candidates
            if all(column in schema and schema[column] == pl.Date for schema in schemas)
        ),
        None,
    )
    common_symbol = all("symbol" in schema for schema in schemas)
    scans: list[pl.LazyFrame] = []
    for file_index, (path, schema) in enumerate(zip(files, schemas, strict=True)):
        scan = pl.scan_parquet(path)
        if wanted is not None:
            read_cols = [column for column in schema if column in wanted]
            if not read_cols:
                scans.append(scan.select([]))
                continue
            scan = scan.select(read_cols)
        scan = scan.with_row_index("__catalog_source_row")
        scan = scan.with_columns(pl.lit(file_index).alias("__catalog_source_file"))
        if common_date is not None:
            if start_date is not None:
                scan = scan.filter(pl.col(common_date) >= start_date)
            if end_date is not None:
                scan = scan.filter(pl.col(common_date) <= end_date)
        if symbols and common_symbol:
            scan = scan.filter(pl.col("symbol").is_in(symbols))
        scans.append(scan)

    try:
        _validate_lazy_schema_versions(files)
        frame = pl.concat(scans, how="diagonal_relaxed").collect()
    except DataValidationError:
        raise
    except Exception as exc:
        logger.error(f"DataCatalog Lazy 读取文件失败 [{files}]: {exc}")
        raise StorageError(f"DataCatalog 读取文件失败 [{files}]: {exc}") from exc
    order_columns = [
        column
        for column in ("__catalog_source_file", "__catalog_source_row")
        if column in frame.columns
    ]
    if order_columns:
        frame = frame.sort(order_columns).drop(order_columns)
    frame = normalize_read_frame(dataset, frame)
    validate_schema_version(frame, files)
    return finalize_dataset_frame(
        frame,
        dataset,
        data_source,
        date_candidates=date_candidates,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )


def _validate_lazy_schema_versions(files: Sequence[Path]) -> None:
    for path in files:
        schema = pl.read_parquet_schema(path)
        if "schema_version" not in schema:
            continue
        frame = pl.scan_parquet(path).select("schema_version").collect()
        validate_schema_version(frame, path)


def finalize_dataset_frame(
    df: pl.DataFrame,
    dataset: str,
    data_source: str,
    *,
    date_candidates: Sequence[str],
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
) -> pl.DataFrame:
    """执行 eager 与 Lazy 共用的最终归一、日期和标的过滤。"""
    if df.is_empty():
        return df
    df = normalize_identity_columns(df)
    date_column = next((column for column in date_candidates if column in df.columns), None)
    if date_column is not None and (start_date is not None or end_date is not None):
        df = df.with_columns(_business_date_expr(date_column).alias("__catalog_date"))
        if start_date is not None:
            df = df.filter(pl.col("__catalog_date") >= start_date)
        if end_date is not None:
            df = df.filter(pl.col("__catalog_date") <= end_date)
        df = df.drop("__catalog_date")
    if symbols and "symbol" in df.columns:
        df = df.filter(pl.col("symbol").is_in(symbols))
    if data_source == "tushare" and dataset == "margin":
        df = filter_complete_margin_dates(df, start_date=start_date, end_date=end_date)
    return df


def _business_date_expr(column: str) -> pl.Expr:
    if column == "month":
        return (
            pl.col(column)
            .cast(pl.Utf8, strict=False)
            .str.slice(0, 6)
            .str.strptime(pl.Date, "%Y%m", strict=False)
        )
    if column == "quarter":
        text = pl.col(column).cast(pl.Utf8, strict=False)
        year = text.str.extract(r"^(\\d{4})Q[1-4]$", 1).cast(pl.Int32, strict=False)
        quarter = text.str.extract(r"^\\d{4}Q([1-4])$", 1).cast(pl.Int32, strict=False)
        return pl.date(year, (quarter - 1) * 3 + 1, 1)
    from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

    return parse_mixed_date(column)


def normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
    """将目录内部使用的标的与日期别名归一化。"""
    columns = set(df.columns)
    result = df
    for alias in _IDENTITY_ALIASES:
        if alias not in columns:
            continue
        if "symbol" not in columns:
            result = result.rename({alias: "symbol"})
        else:
            result = result.with_columns(
                pl.coalesce(
                    [
                        pl.col("symbol").cast(pl.Utf8, strict=False),
                        pl.col(alias).cast(pl.Utf8, strict=False),
                    ]
                ).alias("symbol")
            ).drop(alias)
        columns = set(result.columns)

    for alias in _DATE_ALIASES:
        if alias not in columns:
            continue
        if "trade_date" not in columns:
            result = result.rename({alias: "trade_date"})
        else:
            result = result.with_columns(
                pl.coalesce(
                    [
                        pl.col("trade_date").cast(pl.Utf8, strict=False),
                        pl.col("date").cast(pl.Utf8, strict=False),
                    ]
                ).alias("trade_date")
            ).drop(alias)
        columns = set(result.columns)
    return result


__all__ = [
    "finalize_dataset_frame",
    "normalize_identity_columns",
    "read_columns",
    "read_dataset_files_lazy",
    "should_use_lazy_read",
]
