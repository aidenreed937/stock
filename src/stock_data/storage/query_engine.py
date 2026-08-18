"""DuckDB 内存查询引擎 (DuckDBQueryEngine)。"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock_core.utils.logger import logger
from stock_data.storage.compat import StorageCompat
from stock_data.storage.read_compat import (
    normalize_read_frame,
    requires_read_normalization,
    validate_schema_version,
)
from stock_data.storage.sql_templates import (
    build_daily_bars_sql,
    build_history_sql,
    build_read_parquet_sql,
    build_snapshot_sql,
)


def _infer_dataset_name(
    matched_files: Sequence[str | Path], default: str = "stock_daily_bar"
) -> str:
    """从标准 market=<...>/<dataset>/... 路径推断数据集名。"""
    for file_path in matched_files:
        parts = Path(file_path).parts
        for index, part in enumerate(parts[:-1]):
            if part.startswith("market="):
                candidate = parts[index + 1]
                if not candidate.startswith(("year=", "month=")):
                    return candidate
    return default


def _requires_compatibility_read(matched_files: Sequence[str | Path], dataset_name: str) -> bool:
    """判断是否必须先经过统一历史字段归一化再查询。"""
    for file_path in matched_files:
        if requires_read_normalization(Path(file_path), dataset_name):
            return True
    return False


def _read_compatible_frames(matched_files: Sequence[str | Path], dataset_name: str) -> pl.DataFrame:
    """读取并按统一兼容层归一化一组历史 Parquet 文件。"""
    frames: list[pl.DataFrame] = []
    for file_path in matched_files:
        frame = pl.read_parquet(file_path)
        frame = normalize_read_frame(dataset_name, frame)
        validate_schema_version(frame, file_path)
        frames.append(frame)
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _filter_compatible_frame(
    df: pl.DataFrame,
    *,
    symbol: str | None = None,
    data_source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
    min_price: float | None = None,
) -> pl.DataFrame:
    """在统一字段上执行 DuckDB 查询入口的过滤条件。"""
    result = df
    if symbol is not None and "symbol" in result.columns:
        result = result.filter(pl.col("symbol") == symbol)
    if symbols and "symbol" in result.columns:
        result = result.filter(pl.col("symbol").is_in(symbols))
    if data_source is not None and "data_source" in result.columns:
        result = result.filter(pl.col("data_source") == data_source)
    if "trade_date" in result.columns:
        if start_date is not None:
            result = result.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            result = result.filter(pl.col("trade_date") <= end_date)
    if min_price is not None and "close" in result.columns:
        result = result.filter(pl.col("close") >= min_price)
    sort_columns = [column for column in ("trade_date", "symbol") if column in result.columns]
    return result.sort(sort_columns) if sort_columns else result


class DuckDBQueryEngine:
    """维护 DuckDB 内存连接并执行高性能 SQL / Arrow 数据集检索。"""

    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self.conn = conn or duckdb.connect(database=":memory:")

    def query_by_sql(self, sql_query: str) -> pl.DataFrame:
        """执行通用 SQL 查询并返回 Polars DataFrame。"""
        arrow_table = self.conn.execute(sql_query).to_arrow_table()
        return pl.from_arrow(arrow_table)  # type: ignore

    def query_dataset(
        self,
        matched_files: Sequence[str | Path],
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        dataset_name: str | None = None,
    ) -> pl.DataFrame:
        """根据 Parquet 路径列表与过滤条件查询标准数据集。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
            return pl.DataFrame()
        resolved_dataset = dataset_name or _infer_dataset_name(str_files)
        if _requires_compatibility_read(str_files, resolved_dataset):
            try:
                return _filter_compatible_frame(
                    _read_compatible_frames(str_files, resolved_dataset),
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as e:
                logger.error(f"DuckDB 兼容数据集查询异常: {e}")
                return pl.DataFrame()
        conditions, order_clause = StorageCompat.build_dataset_query_clause(
            str_files, symbol=symbol, start_date=start_date, end_date=end_date
        )
        sql = build_read_parquet_sql(str_files, conditions=conditions, order_clause=order_clause)
        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 数据集查询异常: {e}")
            return pl.DataFrame()

    def query_daily_bars(
        self,
        matched_files: Sequence[str | Path],
        symbol: str,
        data_source: str,
        min_price: float | None = None,
        dataset_name: str | None = None,
    ) -> pl.DataFrame:
        """检索单只标的的日线行情数据。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
            return pl.DataFrame()
        resolved_dataset = dataset_name or _infer_dataset_name(str_files)
        if _requires_compatibility_read(str_files, resolved_dataset):
            try:
                return _filter_compatible_frame(
                    _read_compatible_frames(str_files, resolved_dataset),
                    symbol=symbol,
                    data_source=data_source,
                    min_price=min_price,
                )
            except Exception as e:
                logger.error(f"DuckDB 兼容日线查询异常: {e}")
                return pl.DataFrame()
        sql = build_daily_bars_sql(
            matched_files=str_files,
            symbol=symbol,
            data_source=data_source,
            min_price=min_price,
        )
        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 日线查询异常: {e}")
            return pl.DataFrame()

    def query_history(
        self,
        matched_files: Sequence[str | Path],
        data_source: str,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        dataset_name: str | None = None,
    ) -> pl.DataFrame:
        """检索面板历史数据切片。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
            return pl.DataFrame()
        resolved_dataset = dataset_name or _infer_dataset_name(str_files)
        if _requires_compatibility_read(str_files, resolved_dataset):
            try:
                return _filter_compatible_frame(
                    _read_compatible_frames(str_files, resolved_dataset),
                    data_source=data_source,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                )
            except Exception as e:
                logger.error(f"DuckDB 兼容历史查询异常: {e}")
                return pl.DataFrame()
        sql = build_history_sql(
            matched_files=str_files,
            data_source=data_source,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 面板查询异常: {e}")
            return pl.DataFrame()

    def query_universe_snapshots(
        self, matched_files: Sequence[str | Path], as_of_date: date | str | None = None
    ) -> pl.DataFrame:
        """查询已落盘归档的选股池历史快照。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
            return pl.DataFrame()
        sql = build_snapshot_sql(matched_files=str_files, as_of_date=as_of_date)
        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 选股快照查询异常: {e}")
            return pl.DataFrame()
