from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock.config.settings import settings
from stock.utils.logger import logger


class DuckDBMarketStore:
    """基于 DuckDB + Parquet 的本地极速行情存储引擎"""

    def __init__(self, storage_dir: Path | str | None = None):
        if storage_dir is None:
            self.storage_dir = settings.curated_data_dir
        else:
            self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(database=":memory:")

    def _get_partition_dir(self, endpoint: str, target_date: date) -> Path:
        """根据接口名与日期计算 Hive 时间分区目录路径。"""
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.storage_dir / endpoint / year_str / month_str

    def get_parquet_path(self, endpoint: str, target_date: date) -> Path:
        """计算归档文件路径。"""
        partition_dir = self._get_partition_dir(endpoint, target_date)
        date_str = target_date.strftime("%Y%m%d")
        return partition_dir / f"{endpoint}_{date_str}.parquet"

    def has_curated(self, endpoint: str, target_date: date) -> bool:
        """检查某天的数据是否已被精炼并落盘。"""
        return self.get_parquet_path(endpoint, target_date).exists()

    def save_market_data(self, endpoint: str, target_date: date, df: pl.DataFrame) -> Path:
        """保存精炼数据到指定的时间分区。"""
        file_path = self.get_parquet_path(endpoint, target_date)
        if df.is_empty():
            logger.warning(f"数据帧为空，跳过精炼存储 [{endpoint}]")
            return file_path

        file_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(file_path)
        logger.info(f"精炼数据落盘成功 [{endpoint}] -> {file_path} ({len(df)} 行)")
        return file_path

    def query_by_sql(self, sql_query: str) -> pl.DataFrame:
        """执行通用 SQL 查询并返回 Polars DataFrame"""
        arrow_table = self.conn.execute(sql_query).to_arrow_table()
        return pl.from_arrow(arrow_table)  # type: ignore

    def query_daily_bars(
        self, symbol: str, endpoint: str = "daily", min_price: float | None = None
    ) -> pl.DataFrame:
        """使用 DuckDB SQL 快速检索全量分区数据中的单只股票。"""
        search_pattern = str(self.storage_dir / endpoint / "*" / "*" / "*.parquet")
        # 简单检查是否存在文件（不精确，仅确保 duckdb 不报找不到文件错）
        if not list(self.storage_dir.rglob("*.parquet")):
            logger.warning(f"本地无 {endpoint} 分区 Parquet 缓存文件")
            return pl.DataFrame()

        sql = f"SELECT * FROM '{search_pattern}' WHERE symbol = '{symbol}'"  # noqa: S608
        if min_price is not None:
            sql += f" AND close >= {min_price}"
        sql += " ORDER BY trade_date ASC"

        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 查询异常: {e}")
            return pl.DataFrame()

    def query_history(
        self,
        endpoint: str = "daily",
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        """检索全量或部分标的在指定时间段内的历史数据切片。"""
        search_pattern = str(self.storage_dir / endpoint / "*" / "*" / "*.parquet")
        if not list(self.storage_dir.rglob("*.parquet")):
            logger.warning(f"本地无 {endpoint} 分区 Parquet 缓存文件")
            return pl.DataFrame()

        conditions = []
        if start_date:
            conditions.append(f"trade_date >= '{start_date.strftime('%Y-%m-%d')}'")
        if end_date:
            conditions.append(f"trade_date <= '{end_date.strftime('%Y-%m-%d')}'")
        if symbols:
            symbols_str = ", ".join(f"'{s}'" for s in symbols)
            conditions.append(f"symbol IN ({symbols_str})")

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM '{search_pattern}'{where_clause} ORDER BY trade_date ASC, symbol ASC"  # noqa: S608

        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 面板查询异常: {e}")
            return pl.DataFrame()

