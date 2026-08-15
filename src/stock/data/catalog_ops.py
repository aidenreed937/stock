"""DataCatalog 文件扫描与校验辅助函数。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.data.storage.compat import StorageCompat
from stock.exceptions import DataValidationError

_IDENTITY_ALIASES = ("ts_code", "stockCode", "code")
_DATE_ALIASES = ("date",)


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


def scan_latest_trade_dates(files: list[Path], n: int = 1) -> list[date]:
    if not files:
        return []
    found: set[date] = set()
    for path in reversed(files):
        try:
            df_lazy = pl.scan_parquet(path)
            cols = df_lazy.collect_schema().names()
            date_col = next((c for c in ("trade_date", "date", "Date") if c in cols), None)
            if not date_col:
                continue
            distinct_df = StorageCompat.safe_cast_date_col(
                df_lazy.select(pl.col(date_col).drop_nulls().unique()).collect(), date_col
            )
            for d in distinct_df[date_col].to_list():
                if isinstance(d, date):
                    found.add(d)
        except Exception:
            continue
    return sorted(found, reverse=True)[:n]


def validate_schema_version(df: pl.DataFrame, path: Path) -> None:
    if "schema_version" not in df.columns or df.is_empty():
        return
    versions = {
        str(v)
        for v in df.get_column("schema_version")
        .cast(pl.Utf8, strict=False)
        .drop_nulls()
        .unique()
        .to_list()
        if str(v)
    }
    invalid = versions - {"v2"}
    if invalid:
        raise DataValidationError(f"文件 [{path}] 包含旧版或未知 schema_version: {sorted(invalid)}")
