from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock.config.loader import load_data_config
from stock.config.settings import settings
from stock.data.contracts import DAILY_BAR_CONTRACT, DatasetKey, get_endpoint_market
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
        self._batch_mode = False
        self._write_buffer: dict[Path, list[pl.DataFrame]] = {}
        import threading

        self._file_lock = threading.Lock()
        self._curated_cache: dict[Path, pl.DataFrame] = {}

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

    def enable_batch_mode(self) -> None:
        """开启内存攒批写入模式，避免循环单日/单标的追加写入造成的 O(N^2) 写放大。"""
        self._batch_mode = True
        self._write_buffer = {}
        logger.info("DuckDBMarketStore 已开启攒批写入模式 (Micro-batching)")

    def commit(self) -> None:
        """提交并刷新所有攒批缓存到本地 Parquet，执行合并去重。"""
        if not getattr(self, "_batch_mode", False):
            return

        if not getattr(self, "_write_buffer", {}):
            self._batch_mode = False
            return

        logger.info(f"开始提交攒批数据，共涉及 {len(self._write_buffer)} 个目标文件分区...")
        for file_path, dfs in self._write_buffer.items():
            if not dfs:
                continue
            merged = self._merge_and_save_parquet(file_path, dfs)
            logger.info(f"攒批合并落盘成功 -> {file_path} (合并后共 {len(merged)} 行)")

        self._write_buffer.clear()
        self._batch_mode = False
        logger.info("攒批提交完成，已自动关闭攒批模式。")

    def _merge_and_save_parquet(
        self, file_path: Path, dfs: list[pl.DataFrame], source: str | None = None
    ) -> pl.DataFrame:
        """读取现有文件、合并新数据帧列表、进行去重与排序，并原子写入 Parquet。"""
        if not hasattr(self, "_file_lock"):
            import threading

            self._file_lock = threading.Lock()

        with self._file_lock:
            existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
            if not existing.is_empty() and source is not None:
                self._validate_frame_source(existing, source, f"已有 Curated 文件 [{file_path}]")
                for df in dfs:
                    if set(existing.columns) != set(df.columns):
                        raise DataValidationError(
                            f"Curated 文件 schema 不匹配 [{file_path}]: "
                            f"已有列 {existing.columns}，新数据列 {df.columns}"
                        )

            all_dfs = ([existing] + dfs) if not existing.is_empty() else dfs
            merged = pl.concat(all_dfs, how="diagonal_relaxed")

            dedup_cols = [
                c
                for c in [
                    "market",
                    "exchange_id",
                    "symbol",
                    "stockCode",
                    "ts_code",
                    "code",
                    "trade_date",
                    "date",
                    "adjustment",
                ]
                if c in merged.columns
            ]
            if dedup_cols:
                merged = merged.unique(subset=dedup_cols, keep="last")
            if "trade_date" in merged.columns and "symbol" in merged.columns:
                merged = merged.sort(["trade_date", "symbol"])

            file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = file_path.with_suffix(".tmp.parquet")
            merged.write_parquet(temp_path)
            temp_path.replace(file_path)

            # 同步更新 LRU 内存缓存并限制容量上限 <= 128
            if hasattr(self, "_curated_cache"):
                if len(self._curated_cache) > 128:
                    # 超过 128 个缓存文件句柄时剔除最早插入的项
                    first_key = next(iter(self._curated_cache))
                    del self._curated_cache[first_key]
                self._curated_cache[file_path] = merged

        return merged

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

    def _get_partition_dir(self, endpoint: str, target_date: date, market: str = "MULTI") -> Path:
        """根据接口名与日期计算 Hive 时间与市场分区目录路径。"""
        market_slug = f"market={market.upper()}"
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.storage_dir / market_slug / endpoint / year_str / month_str

    def get_parquet_path(self, endpoint: str, target_date: date, market: str = "MULTI") -> Path:
        """计算归档文件路径（按市场与月份统一为 data.parquet）。"""
        partition_dir = self._get_partition_dir(endpoint, target_date, market=market)
        return partition_dir / "data.parquet"

    def has_curated(
        self, endpoint: str, target_date: date, symbol: str | None = None
    ) -> bool:
        """检查某天（及可选指定股票）的数据是否已被精炼并落盘。"""
        data_source = self._require_data_source()
        if endpoint in {"daily", "daily_bar"}:
            endpoints = ["daily_bar", "stock_daily_bar", "index_daily_bar"]
        else:
            endpoints = [endpoint]
        year_month_path = f"year={target_date.year:04d}/month={target_date.month:02d}"
        matching_files: list[Path] = []
        for ep in endpoints:
            matching_files.extend(self.storage_dir.glob(f"**/{ep}/{year_month_path}/*.parquet"))
        if not matching_files:
            return False
        date_str_hyphen = target_date.strftime("%Y-%m-%d")
        date_str_plain = target_date.strftime("%Y%m%d")
        if not hasattr(self, "_curated_cache"):
            self._curated_cache = {}

        for file_path in matching_files:
            try:
                if file_path not in self._curated_cache:
                    self._curated_cache[file_path] = pl.read_parquet(file_path)
                df = self._curated_cache[file_path]

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
                        elif (
                            not symbol
                            and "symbol" in df.columns
                            and (
                                "stock_daily_bar" in str(file_path)
                                or ("daily_bar" in str(file_path) and "index" not in str(file_path) and "fund" not in str(file_path))
                            )
                        ):
                            # 全市场日线行情回填时，如果当前文件中的该日期含有的个股数少于对应年份的最小预期股票数，不判定为已归档
                            matched_val: date | str | None = None
                            if target_date in dates:
                                matched_val = target_date
                            elif date_str_hyphen in dates:
                                matched_val = date_str_hyphen
                            elif date_str_plain in dates:
                                matched_val = date_str_plain

                            if matched_val is not None:
                                day_df = df.filter(pl.col("trade_date") == matched_val)

                                # 根据年份动态设定全市场最小股票数量阈值（防历史早期个股偏少导致死循环）
                                if target_date.year < 1993:
                                    min_symbols = 5
                                elif target_date.year < 1996:
                                    min_symbols = 50
                                elif target_date.year < 2000:
                                    min_symbols = 300
                                else:
                                    min_symbols = 800

                                if len(day_df["symbol"].unique()) < min_symbols:
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
        """保存行情数据 (对齐 save_curated 别名)。"""
        return self.save_curated(df=df, endpoint=endpoint, target_date=target_date, data_source=data_source)

    def _save_dataframe_partitioned(
        self,
        df: pl.DataFrame,
        dataset_name: str,
        fallback_date: date,
        market_code: str,
        source: str,
    ) -> Path:
        """根据数据帧内部的真实交易日 (trade_date/date) 动态分桶路由落盘。"""
        config = load_data_config()
        no_part_providers = set(config.storage.raw.non_partitioned_providers)
        no_part_datasets = set(config.storage.raw.non_partitioned_datasets)

        if source in no_part_providers or dataset_name in no_part_datasets:
            file_path = (
                self.storage_dir
                / f"market={market_code.upper()}"
                / dataset_name
                / "data.parquet"
            )
            self._save_single_partition(file_path, df, dataset_name, source)
            return file_path

        date_col = next(
            (c for c in ["trade_date", "date", "as_of_date", "Date"] if c in df.columns), None
        )
        if not date_col or df.is_empty():
            file_path = self.get_parquet_path(dataset_name, fallback_date, market=market_code)
            self._save_single_partition(file_path, df, dataset_name, source)
            return file_path

        try:
            parsed_df = df.with_columns(
                pl.col(date_col)
                .cast(pl.Utf8)
                .str.slice(0, 10)
                .str.to_date("%Y-%m-%d", strict=False)
                .alias("_parsed_date")
            )
            if parsed_df["_parsed_date"].null_count() == len(parsed_df):
                parsed_df = df.with_columns(
                    pl.col(date_col)
                    .cast(pl.Utf8)
                    .str.to_date("%Y%m%d", strict=False)
                    .alias("_parsed_date")
                )

            valid_df = parsed_df.filter(pl.col("_parsed_date").is_not_null())
            if valid_df.is_empty():
                file_path = self.get_parquet_path(dataset_name, fallback_date, market=market_code)
                self._save_single_partition(file_path, df, dataset_name, source)
                return file_path

            grouped = valid_df.with_columns(
                [
                    pl.col("_parsed_date").dt.year().alias("_part_year"),
                    pl.col("_parsed_date").dt.month().alias("_part_month"),
                ]
            )

            ym_pairs = grouped.select(["_part_year", "_part_month"]).unique().iter_rows()
            last_path = None
            for yr, mo in ym_pairs:
                if yr is None or mo is None:
                    continue
                sub_df = grouped.filter(
                    (pl.col("_part_year") == yr) & (pl.col("_part_month") == mo)
                ).drop(["_parsed_date", "_part_year", "_part_month"])

                sub_date = date(int(yr), int(mo), 1)
                sub_path = self.get_parquet_path(dataset_name, sub_date, market=market_code)
                self._save_single_partition(sub_path, sub_df, dataset_name, source)
                last_path = sub_path

            return last_path or self.get_parquet_path(
                dataset_name, fallback_date, market=market_code
            )
        except Exception as e:
            logger.warning(f"动态按交易日拆分落盘异常，降级使用统一时间分区: {e}")
            file_path = self.get_parquet_path(dataset_name, fallback_date, market=market_code)
            self._save_single_partition(file_path, df, dataset_name, source)
            return file_path

    def _save_single_partition(
        self, file_path: Path, df: pl.DataFrame, dataset_name: str, source: str
    ) -> None:
        if getattr(self, "_batch_mode", False):
            if file_path not in getattr(self, "_write_buffer", {}):
                self._write_buffer[file_path] = []
            self._write_buffer[file_path].append(df)
            logger.debug(f"已加入攒批写入缓存 [{dataset_name}] -> {file_path}")
        else:
            merged = self._merge_and_save_parquet(file_path, [df], source=source)
            logger.info(f"精炼数据落盘成功 [{dataset_name}] -> {file_path} ({len(merged)} 行)")

    def save_curated(
        self,
        df: pl.DataFrame,
        endpoint: str,
        target_date: date,
        data_source: str | None = None,
    ) -> Path:
        """保存精炼数据到指定的时间分区。"""
        if endpoint == "daily":
            endpoint = "daily_bar"
        source = data_source or self.data_source
        if source is None and "data_source" in df.columns:
            sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
            if len(sources) == 1:
                source = next(iter(sources))
        if source is None:
            raise DataValidationError("Curated 数据缺少数据源，拒绝写入未绑定来源的数据")
        self.bind_data_source(source)

        market_code = get_endpoint_market(source, endpoint)
        if "market" in df.columns and not df.is_empty():
            m_values = set(df.get_column("market").drop_nulls().unique().to_list())
            if len(m_values) == 1 and next(iter(m_values)):
                market_code = next(iter(m_values))

        if df.is_empty():
            file_path = self.get_parquet_path(endpoint, target_date, market=market_code)
            logger.warning(f"数据帧为空，跳过精炼存储 [{endpoint}]")
            return file_path

        file_path = self.get_parquet_path(endpoint, target_date, market=market_code)
        self._validate_frame_source(df, source, f"Curated 数据 [{file_path}]")
        if endpoint in {"daily", "daily_bar"}:
            DAILY_BAR_CONTRACT.validate(df)

        return self._save_dataframe_partitioned(
            df=df,
            dataset_name=endpoint,
            fallback_date=target_date,
            market_code=market_code,
            source=source,
        )

    def save_dataset(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        """按数据集和业务日期幂等合并保存标准数据。"""
        self.bind_data_source(key.provider)
        market_code = (
            key.instrument.market
            if key.instrument and key.instrument.market
            else get_endpoint_market(key.provider, key.dataset)
        )
        if "market" in df.columns and not df.is_empty():
            m_values = set(df.get_column("market").drop_nulls().unique().to_list())
            if len(m_values) == 1 and next(iter(m_values)):
                market_code = next(iter(m_values))
        file_path = self.get_parquet_path(key.dataset, key.end_date, market=market_code)
        if df.is_empty():
            return file_path
        self._validate_frame_source(df, key.provider, f"Curated 数据 [{file_path}]")
        if key.dataset == "daily_bar":
            DAILY_BAR_CONTRACT.validate(df)

        return self._save_dataframe_partitioned(
            df=df,
            dataset_name=key.dataset,
            fallback_date=key.end_date,
            market_code=market_code,
            source=key.provider,
        )

    def query_dataset(
        self,
        dataset: str = "daily_bar",
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """查询标准数据集，兼容旧 endpoint 查询入口。"""
        data_source = self._require_data_source()
        target_dataset = "*daily_bar" if dataset in {"daily_bar", "daily"} else dataset
        search_pattern = str(self.storage_dir / "**" / target_dataset / "*" / "*" / "*.parquet")
        if not list(self.storage_dir.rglob("*.parquet")):
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
        if endpoint == "daily":
            return self.query_dataset(dataset="daily_bar", symbol=symbol)
        search_pattern = str(self.storage_dir / "**" / endpoint / "*" / "*" / "*.parquet")
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
        search_pattern = str(self.storage_dir / "**" / endpoint / "*" / "*" / "*.parquet")
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
