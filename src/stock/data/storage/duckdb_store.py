from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock.config.settings import settings
from stock.data.contracts import DAILY_BAR_CONTRACT, DatasetKey
from stock.exceptions import DataValidationError
from stock.utils.logger import logger


class DuckDBMarketStore:
    """基于 DuckDB + Parquet 的本地极速行情存储引擎"""

    def __init__(
        self, storage_dir: Path | str | None = None, data_source: str | None = None
    ) -> None:
        """初始化 Curated 存储，并按数据源隔离默认目录。"""
        self.data_source = data_source
        self._storage_root = (
            Path(storage_dir) if storage_dir is not None else settings.curated_data_dir
        )
        if self.data_source is None and storage_dir is None:
            self.data_source = settings.data_source_mode
        self.storage_dir = self._get_source_dir()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(database=":memory:")

    def _get_source_dir(self) -> Path:
        """返回当前数据源专属的 Curated 目录。"""
        return self._storage_root / self.data_source if self.data_source else self._storage_root

    def _require_data_source(self) -> str:
        """要求存储实例已绑定数据源，避免读取未隔离目录。"""
        if self.data_source is None:
            raise DataValidationError("Curated 存储未绑定数据源，拒绝读取未隔离目录")
        return self.data_source

    def bind_data_source(self, data_source: str) -> None:
        """绑定存储的数据源，防止同一实例混写不同来源。"""
        if self.data_source is None:
            self.data_source = data_source
            self.storage_dir = self._get_source_dir()
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        elif self.data_source != data_source:
            raise DataValidationError(
                f"Curated 存储数据源不匹配: 已绑定 [{self.data_source}]，收到 [{data_source}]"
            )

    def _validate_frame_source(self, df: pl.DataFrame, data_source: str, context: str) -> None:
        """校验数据帧的血统元数据。"""
        if "data_source" not in df.columns:
            raise DataValidationError(f"{context}缺少 data_source 血统字段")
        source_column = df.get_column("data_source")
        if source_column.null_count() > 0:
            raise DataValidationError(f"{context}包含空 data_source 血统字段")
        sources = set(source_column.unique().to_list())
        if sources != {data_source}:
            raise DataValidationError(
                f"{context}数据源不匹配: 期望 [{data_source}]，实际 [{sorted(sources)}]"
            )

    def _get_partition_dir(self, endpoint: str, target_date: date) -> Path:
        """根据接口名与日期计算 Hive 时间分区目录路径。"""
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.storage_dir / endpoint / year_str / month_str

    def get_parquet_path(self, endpoint: str, target_date: date) -> Path:
        """计算归档文件路径（按月份统一为 data.parquet）。"""
        partition_dir = self._get_partition_dir(endpoint, target_date)
        return partition_dir / "data.parquet"

    def has_curated(
        self, endpoint: str, target_date: date, symbol: str | None = None
    ) -> bool:
        """检查某天（及可选指定股票）的数据是否已被精炼并落盘。"""
        data_source = self._require_data_source()
        if endpoint == "daily":
            endpoint = "daily_bar"
        partition_dir = self._get_partition_dir(endpoint, target_date)
        if not partition_dir.exists():
            return False
        date_str_hyphen = target_date.strftime("%Y-%m-%d")
        date_str_plain = target_date.strftime("%Y%m%d")
        for file_path in partition_dir.glob("*.parquet"):
            try:
                df = pl.read_parquet(file_path)
                self._validate_frame_source(df, data_source, f"Curated 文件 [{file_path}]")
                if "trade_date" in df.columns:
                    dates = set(df["trade_date"].unique().to_list())
                    if (
                        target_date in dates
                        or date_str_hyphen in dates
                        or date_str_plain in dates
                    ):
                        if symbol and "symbol" in df.columns:
                            symbols = set(df["symbol"].unique().to_list())
                            if symbol not in symbols:
                                continue
                        return True
            except Exception as e:
                logger.warning(f"忽略无效 Curated 缓存 [{file_path}]: {e}")
                continue
        return False

    def save_market_data(
        self,
        endpoint: str,
        target_date: date,
        df: pl.DataFrame,
        data_source: str | None = None,
    ) -> Path:
        """保存精炼数据到指定的时间分区。"""
        if df.is_empty():
            file_path = self.get_parquet_path(endpoint, target_date)
            logger.warning(f"数据帧为空，跳过精炼存储 [{endpoint}]")
            return file_path

        source = data_source or self.data_source
        if source is None and "data_source" in df.columns:
            sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
            if len(sources) == 1:
                source = next(iter(sources))
        if source is None:
            raise DataValidationError("Curated 数据缺少数据源，拒绝写入未绑定来源的数据")
        self.bind_data_source(source)
        file_path = self.get_parquet_path(endpoint, target_date)
        self._validate_frame_source(df, source, f"Curated 数据 [{file_path}]")
        if endpoint in {"daily", "daily_bar"}:
            DAILY_BAR_CONTRACT.validate(df)
        existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
        if not existing.is_empty():
            self._validate_frame_source(existing, source, f"已有 Curated 文件 [{file_path}]")
            if existing.schema != df.schema:
                raise DataValidationError(
                    f"Curated 文件 schema 不匹配 [{file_path}]: "
                    f"已有列 {existing.columns}，新数据列 {df.columns}"
                )

        file_path.parent.mkdir(parents=True, exist_ok=True)
        merged = pl.concat([existing, df], how="diagonal") if not existing.is_empty() else df
        dedup_cols = [
            c for c in ["market", "symbol", "stockCode", "ts_code", "code", "trade_date", "date", "adjustment"] if c in merged.columns
        ]
        if dedup_cols:
            merged = merged.unique(subset=dedup_cols, keep="last")
        if "trade_date" in merged.columns and "symbol" in merged.columns:
            merged = merged.sort(["trade_date", "symbol"])
        temp_path = file_path.with_suffix(".tmp.parquet")
        merged.write_parquet(temp_path)
        temp_path.replace(file_path)
        logger.info(f"精炼数据落盘成功 [{endpoint}] -> {file_path} ({len(merged)} 行)")
        return file_path

    def save_dataset(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        """按数据集和业务日期幂等合并保存标准数据。"""
        self.bind_data_source(key.provider)
        file_path = self.get_parquet_path(key.dataset, key.end_date)
        if df.is_empty():
            return file_path
        self._validate_frame_source(df, key.provider, f"Curated 数据 [{file_path}]")
        if key.dataset == "daily_bar":
            DAILY_BAR_CONTRACT.validate(df)
        existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
        if not existing.is_empty():
            self._validate_frame_source(existing, key.provider, f"已有 Curated 文件 [{file_path}]")
            if existing.schema != df.schema:
                raise DataValidationError(
                    f"Curated 文件 schema 不匹配 [{file_path}]: "
                    f"已有列 {existing.columns}，新数据列 {df.columns}"
                )
        merged = pl.concat([existing, df], how="diagonal") if not existing.is_empty() else df
        dedup_cols = [
            c for c in ["market", "symbol", "stockCode", "ts_code", "code", "trade_date", "date", "adjustment"] if c in merged.columns
        ]
        if dedup_cols:
            merged = merged.unique(subset=dedup_cols, keep="last")
        if "trade_date" in merged.columns and "symbol" in merged.columns:
            merged = merged.sort(["trade_date", "symbol"])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_suffix(".tmp.parquet")
        merged.write_parquet(temp_path)
        temp_path.replace(file_path)
        return file_path

    def query_dataset(
        self,
        dataset: str = "daily_bar",
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """查询标准数据集，兼容旧 endpoint 查询入口。"""
        data_source = self._require_data_source()
        dataset_dir = self.storage_dir / dataset
        search_pattern = str(dataset_dir / "*" / "*" / "*.parquet")
        if not dataset_dir.exists() or not list(dataset_dir.rglob("*.parquet")):
            return pl.DataFrame()
        conditions: list[str] = []
        if symbol:
            conditions.append(f"symbol = '{symbol}'")
        if start_date:
            conditions.append(f"trade_date >= '{start_date:%Y-%m-%d}'")
        if end_date:
            conditions.append(f"trade_date <= '{end_date:%Y-%m-%d}'")
        conditions.append(f"data_source = '{data_source}'")
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM '{search_pattern}'{where_clause} ORDER BY trade_date ASC, symbol ASC"  # noqa: S608
        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 数据集查询异常: {e}")
            return pl.DataFrame()

    def query_by_sql(self, sql_query: str) -> pl.DataFrame:
        """执行通用 SQL 查询并返回 Polars DataFrame"""
        arrow_table = self.conn.execute(sql_query).to_arrow_table()
        return pl.from_arrow(arrow_table)  # type: ignore

    def query_daily_bars(
        self, symbol: str, endpoint: str = "daily", min_price: float | None = None
    ) -> pl.DataFrame:
        """使用 DuckDB SQL 快速检索全量分区数据中的单只股票。"""
        data_source = self._require_data_source()
        if endpoint == "daily" and (self.storage_dir / "daily_bar").exists():
            return self.query_dataset(dataset="daily_bar", symbol=symbol)
        search_pattern = str(self.storage_dir / endpoint / "*" / "*" / "*.parquet")
        # 简单检查是否存在文件（不精确，仅确保 duckdb 不报找不到文件错）
        if not list(self.storage_dir.rglob("*.parquet")):
            logger.warning(f"本地无 {endpoint} 分区 Parquet 缓存文件")
            return pl.DataFrame()

        sql = f"SELECT * FROM '{search_pattern}' WHERE symbol = '{symbol}'"  # noqa: S608
        sql += f" AND data_source = '{data_source}'"
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
        if endpoint == "daily":
            result = self.query_dataset(
                dataset="daily_bar",
                start_date=start_date,
                end_date=end_date,
            )
            if symbols:
                result = result.filter(pl.col("symbol").is_in(symbols))
            return result
        data_source = self._require_data_source()
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
        conditions.append(f"data_source = '{data_source}'")

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM '{search_pattern}'{where_clause} ORDER BY trade_date ASC, symbol ASC"  # noqa: S608

        try:
            return self.query_by_sql(sql)
        except Exception as e:
            logger.error(f"DuckDB 面板查询异常: {e}")
            return pl.DataFrame()

    def get_max_trade_date(self, symbol: str, endpoint: str = "daily") -> date | None:
        """获取本地已存储该标的最新交易日期。"""
        df = self.query_daily_bars(symbol=symbol, endpoint=endpoint)
        if df.is_empty() or "trade_date" not in df.columns:
            return None
        max_d = df["trade_date"].max()
        if isinstance(max_d, date):
            return max_d
        if isinstance(max_d, str):
            return date.fromisoformat(max_d)
        return None
