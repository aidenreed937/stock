from pathlib import Path

import duckdb
import polars as pl

from stock.config.settings import settings
from stock.constants import DEFAULT_PARQUET_SUBDIR
from stock.utils.logger import logger


class DuckDBMarketStore:
    """基于 DuckDB + Parquet 的本地极速行情存储引擎"""

    def __init__(self, storage_dir: Path | str | None = None):
        if storage_dir is None:
            self.storage_dir = settings.curated_data_dir / DEFAULT_PARQUET_SUBDIR
        else:
            self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(database=":memory:")

    def get_parquet_path(self, symbol: str) -> Path:
        clean_symbol = symbol.replace(".", "_").upper()
        return self.storage_dir / f"daily_{clean_symbol}.parquet"

    def save_daily_bars(self, symbol: str, df: pl.DataFrame) -> Path:
        """保存或增量覆盖指定股票的行情数据到 Parquet"""
        if df.is_empty():
            logger.warning(f"数据帧为空，跳过保存: {symbol}")
            return self.get_parquet_path(symbol)

        file_path = self.get_parquet_path(symbol)
        df.write_parquet(file_path)
        logger.info(f"成功保存行情数据 [{symbol}] -> {file_path} ({len(df)} 行)")
        return file_path

    def query_by_sql(self, sql_query: str) -> pl.DataFrame:
        """执行通用 SQL 查询并返回 Polars DataFrame"""
        arrow_table = self.conn.execute(sql_query).to_arrow_table()
        return pl.from_arrow(arrow_table)  # type: ignore

    def query_daily_bars(
        self, symbol: str, min_price: float | None = None
    ) -> pl.DataFrame:
        """使用 DuckDB SQL 快速检索 Parquet 缓存文件"""
        file_path = self.get_parquet_path(symbol)
        if not file_path.exists():
            logger.warning(f"本地无 Parquet 缓存文件: {file_path}")
            return pl.DataFrame()

        sql = f"SELECT * FROM '{file_path}'"  # noqa: S608
        if min_price is not None:
            sql += f" WHERE close >= {min_price}"
        sql += " ORDER BY trade_date ASC"

        return self.query_by_sql(sql)
