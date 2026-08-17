"""DuckDB 内存查询引擎 (DuckDBQueryEngine)。"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock_core.utils.logger import logger
from stock_data.storage.compat import StorageCompat
from stock_data.storage.sql_templates import (
    build_daily_bars_sql,
    build_history_sql,
    build_read_parquet_sql,
    build_snapshot_sql,
)


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
    ) -> pl.DataFrame:
        """根据 Parquet 路径列表与过滤条件查询标准数据集。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
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
    ) -> pl.DataFrame:
        """检索单只标的的日线行情数据。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
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
    ) -> pl.DataFrame:
        """检索面板历史数据切片。"""
        str_files = [str(p) for p in matched_files]
        if not str_files:
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
