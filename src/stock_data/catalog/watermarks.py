"""Curated 数据集日期与刷新水位扫描工具。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import polars as pl

from stock_data.storage.compat import StorageCompat


def _extract_path_ym(path: Path) -> tuple[int, int] | None:
    year_part = month_part = None
    for part in path.parts:
        if part.startswith("year="):
            try:
                year_part = int(part.removeprefix("year="))
            except ValueError:
                pass
        elif part.startswith("month="):
            try:
                month_part = int(part.removeprefix("month="))
            except ValueError:
                pass
    if year_part is not None:
        return (year_part, month_part or 12)
    return None


def scan_latest_trade_dates(
    files: list[Path],
    n: int = 1,
    symbol: str | None = None,
    date_column: str | None = None,
) -> list[date]:
    """从 Curated 分区扫描最近的业务日期或期间起始日。"""
    if not files:
        return []
    found: set[date] = set()
    current_ym: tuple[int, int] | None = None
    for path in reversed(files):
        ym = _extract_path_ym(path)
        if current_ym is None:
            current_ym = ym
        elif ym is not None and ym < current_ym and len(found) >= n:
            break
        try:
            df_lazy = pl.scan_parquet(path)
            cols = df_lazy.collect_schema().names()
            if symbol and "symbol" in cols:
                df_lazy = df_lazy.filter(pl.col("symbol") == symbol)
            date_candidates = (
                (date_column,)
                if date_column
                else (
                    "trade_date",
                    "report_date",
                    "ann_date",
                    "end_date",
                    "publish_date",
                    "date",
                    "Date",
                    "month",
                    "quarter",
                    "as_of_date",
                    "asOfDate",
                    "endDate",
                    "last_data_date",
                    "period",
                    "Start Date",
                )
            )
            date_col = next((column for column in date_candidates if column in cols), None)
            if not date_col:
                continue
            selected = df_lazy.select(pl.col(date_col).drop_nulls().unique())
            if date_col == "month":
                distinct_df = (
                    selected.with_columns(
                        pl.col(date_col)
                        .cast(pl.Utf8, strict=False)
                        .str.strptime(pl.Date, "%Y%m", strict=False)
                        .alias(date_col)
                    )
                    .drop_nulls()
                    .collect()
                )
            elif date_col == "quarter":
                distinct_df = (
                    selected.with_columns(
                        pl.col(date_col)
                        .cast(pl.Utf8, strict=False)
                        .str.extract(r"^(\d{4})Q([1-4])$", 1)
                        .cast(pl.Int32, strict=False)
                        .alias("__quarter_year"),
                        pl.col(date_col)
                        .cast(pl.Utf8, strict=False)
                        .str.extract(r"^(\d{4})Q([1-4])$", 2)
                        .cast(pl.Int32, strict=False)
                        .alias("__quarter_number"),
                    )
                    .with_columns(
                        pl.date(
                            pl.col("__quarter_year"),
                            (pl.col("__quarter_number") - 1) * 3 + 1,
                            1,
                        ).alias(date_col)
                    )
                    .select(date_col)
                    .drop_nulls()
                    .collect()
                )
            else:
                distinct_df = StorageCompat.safe_cast_date_col(selected.collect(), date_col)
            for value in distinct_df[date_col].to_list():
                if isinstance(value, date):
                    found.add(value)
        except Exception:
            continue
    return sorted(found, reverse=True)[:n]


def scan_latest_refresh_dates(
    files: list[Path],
    n: int = 1,
    symbols: list[str] | None = None,
) -> list[date]:
    """扫描最近刷新日期，缺少有效 updated_at 时回退文件 mtime。"""
    if not files:
        return []

    found: set[date] = set()
    requested_symbols = set(symbols or [])
    for path in files:
        fallback = datetime.fromtimestamp(path.stat().st_mtime).date()
        try:
            schema = pl.read_parquet_schema(path)
            columns: list[str] = [
                column
                for column in ("symbol", "ts_code", "stockCode", "code", "updated_at")
                if column in schema
            ]
            if "updated_at" not in columns:
                found.add(fallback)
                continue

            frame = pl.read_parquet(path, columns=columns)
            symbol_column = next(
                (
                    column
                    for column in ("symbol", "ts_code", "stockCode", "code")
                    if column in frame.columns
                ),
                None,
            )
            if requested_symbols and symbol_column:
                frame = frame.filter(
                    pl.col(symbol_column).cast(pl.Utf8, strict=False).is_in(requested_symbols)
                )
            if frame.is_empty():
                continue

            refresh_values = [
                value
                for value in frame.get_column("updated_at").to_list()
                if isinstance(value, date | datetime) or (isinstance(value, str) and value.strip())
            ]
            parsed = [
                value.date() if isinstance(value, datetime) else value
                for value in refresh_values
                if isinstance(value, date | datetime)
            ]
            if not parsed:
                for value in refresh_values:
                    if not isinstance(value, str):
                        continue
                    parsed_value = _parse_refresh_datetime(value)
                    if parsed_value is not None:
                        parsed.append(parsed_value.date())
            found.add(max(parsed) if parsed else fallback)
        except Exception:
            found.add(fallback)

    return sorted(found, reverse=True)[:n]


def _parse_refresh_datetime(value: str) -> datetime | None:
    """解析历史 updated_at 字符串，仅供刷新水位探测使用。"""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
