from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.exceptions import DataValidationError, StorageError
from stock_core.utils.logger import logger
from stock_data.catalog.watermarks import (
    scan_latest_refresh_dates as _scan_latest_refresh_dates,
)
from stock_data.catalog.watermarks import (
    scan_latest_trade_dates as _scan_latest_trade_dates,
)
from stock_data.governance.quality.margin_coverage import filter_complete_margin_dates
from stock_data.storage.compat import StorageCompat
from stock_data.storage.read_compat import normalize_read_frame, validate_schema_version

_IDENTITY_ALIASES = ("ts_code", "stockCode", "code")
_DATE_ALIASES = ("date",)


def scan_latest_trade_dates(*args: Any, **kwargs: Any) -> list[date]:
    """兼容旧目录工具导入路径。"""
    return _scan_latest_trade_dates(*args, **kwargs)


def scan_latest_refresh_dates(*args: Any, **kwargs: Any) -> list[date]:
    """兼容旧目录工具导入路径。"""
    return _scan_latest_refresh_dates(*args, **kwargs)


def path_intersects_range(path: Path, start_ym: tuple[int, int], end_ym: tuple[int, int]) -> bool:
    year_part = month_part = None
    for part in path.parts:
        if part.startswith("year="):
            try:
                year_part = int(part.removeprefix("year="))
            except ValueError:
                return True
        elif part.startswith("month="):
            try:
                month_part = int(part.removeprefix("month="))
            except ValueError:
                return True
    if year_part is None:
        return True
    if month_part is None:
        return start_ym[0] <= year_part <= end_ym[0]
    return (start_ym[0], start_ym[1]) <= (year_part, month_part) <= (end_ym[0], end_ym[1])


def normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
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


def dataset_name(path: Path) -> str:
    parts = path.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("month=") and i >= 2 and parts[i - 1].startswith("year="):
            return parts[i - 2]
        if parts[i].startswith("year=") and i >= 1:
            return parts[i - 1]
    if not path.parent.name.startswith("market=") and not path.parent.name.startswith("year="):
        return path.parent.name
    return path.stem.split(".", 1)[0]


def list_parquet_files(
    base_dir: Path,
    dataset: str | None = None,
    market: str | None = None,
    artifact_suffixes: tuple[str, ...] = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"),
) -> list[Path]:
    if not base_dir.exists():
        return []
    files: list[Path] = []
    for path in base_dir.rglob("*.parquet"):
        if path.name.casefold().endswith(tuple(suffix.casefold() for suffix in artifact_suffixes)):
            continue
        if dataset is not None and dataset_name(path).casefold() != dataset.casefold():
            continue
        if market is not None and f"market={market.upper()}" not in path.parts:
            continue
        files.append(path)
    return sorted(files)


def read_dataset_files(
    files: list[Path],
    dataset: str,
    data_source: str,
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    if not files:
        logger.warning(
            f"DataCatalog 未找到数据集 [{dataset}] 的 Parquet 文件 (数据源: {data_source})"
        )
        return pl.DataFrame()

    candidate_files = files
    if start_date is not None or end_date is not None:
        start_ym = (start_date.year, start_date.month) if start_date else (date.min.year, 1)
        end_ym = (end_date.year, end_date.month) if end_date else (date.max.year, 12)
        candidate_files = [path for path in files if path_intersects_range(path, start_ym, end_ym)]
        if not candidate_files:
            return pl.DataFrame()

    frames: list[pl.DataFrame] = []
    for path in candidate_files:
        try:
            if columns is not None:
                wanted = set(columns)
                wanted.update(
                    {
                        "symbol",
                        "ts_code",
                        "stockCode",
                        "code",
                        "trade_date",
                        "date",
                        "schema_version",
                        "market",
                        "adjustment",
                        "exchange",
                        "exchange_id",
                    }
                )
                if dataset == "index_valuation":
                    wanted.add("total_assets")
                try:
                    file_schema = pl.read_parquet_schema(path)
                    read_cols = [c for c in file_schema if c in wanted]
                    frame = pl.read_parquet(path, columns=read_cols)
                except Exception:
                    frame = pl.read_parquet(path)
            else:
                frame = pl.read_parquet(path)
        except Exception as e:
            logger.error(f"DataCatalog 读取文件失败 [{path}]: {e}")
            raise StorageError(f"DataCatalog 读取文件失败 [{path}]: {e}") from e
        frame = normalize_read_frame(dataset, frame)
        validate_schema_version(frame, path)
        frames.append(frame)
    if not frames:
        return pl.DataFrame()
    try:
        df = pl.concat(frames, how="diagonal_relaxed")
    except Exception as e:
        logger.error(f"DataCatalog 合并数据集 [{dataset}] 失败: {e}")
        raise StorageError(f"DataCatalog 合并数据集 [{dataset}] 失败: {e}") from e

    if df.is_empty():
        return df

    df = normalize_identity_columns(df)
    if "trade_date" in df.columns:
        df = StorageCompat.safe_cast_date_col(df, "trade_date")
        if start_date is not None:
            df = df.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            df = df.filter(pl.col("trade_date") <= end_date)

    if symbols:
        symbol_col = "symbol" if "symbol" in df.columns else None
        if symbol_col is not None:
            df = df.filter(pl.col(symbol_col).is_in(symbols))

    if data_source == "tushare" and dataset == "margin":
        df = filter_complete_margin_dates(df, start_date=start_date, end_date=end_date)

    return df


def build_catalog_summary(
    catalog: Any, data_source: str | None, market: str | None
) -> pl.DataFrame:
    sources = (
        [d.name for d in catalog.storage_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if (data_source == "all" or data_source is None)
        else [data_source]
    )
    rows: list[dict[str, object]] = []
    for src in sorted(sources):
        try:
            cat = (
                catalog
                if src == catalog.data_source
                else catalog.__class__(data_source=src, storage_dir=catalog.storage_dir)
            )
            for entry in cat.available_datasets(market=market):
                w_date = cat.get_latest_trade_date(entry.dataset, market=market)
                rows.append(
                    {
                        "data_source": src,
                        "dataset": entry.dataset,
                        "files": len(entry.files),
                        "total_rows": entry.total_rows,
                        "latest_date": str(w_date) if w_date else "N/A",
                    }
                )
        except Exception:
            continue
    if rows:
        return pl.DataFrame(rows).sort(["data_source", "dataset"])
    return pl.DataFrame(
        schema={
            "data_source": pl.Utf8,
            "dataset": pl.Utf8,
            "files": pl.Int64,
            "total_rows": pl.Int64,
            "latest_date": pl.Utf8,
        }
    )


def resolve_dataset_alias(data_source: str, name: str) -> str:
    return StorageCompat.canonical_dataset_name(name, data_source)


def validate_bars(df: pl.DataFrame, dataset: str) -> None:
    if dataset not in BAR_DATASETS or df.is_empty():
        return
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return
    if any(df[column].null_count() > 0 for column in required):
        raise DataValidationError(f"数据集 [{dataset}] OHLC 包含空值")
    physical_errors = df.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("high") < pl.col("open"))
        | (pl.col("high") < pl.col("close"))
        | (pl.col("low") > pl.col("open"))
        | (pl.col("low") > pl.col("close"))
    )
    if not physical_errors.is_empty():
        raise DataValidationError(
            f"数据集 [{dataset}] 存在 {len(physical_errors)} 条 OHLC 物理异常"
        )
