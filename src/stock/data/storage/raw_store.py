"""RAW 原始数据离线时间分区归档存储引擎。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock.config.settings import settings
from stock.core.contracts import DatasetKey
from stock.data.storage.compat import StorageCompat
from stock.data.task_registry import get_endpoint_market, resolve_task
from stock.utils.logger import logger


class RawDataStorage:
    """RAW 原始数据存储引擎。

    使用标准的 Hive 风格时间分区归档保存外部 API 原始响应数据:
    路径规范: data/raw/{data_source}/{endpoint}/year={YYYY}/month={MM}/{endpoint}_{YYYYMMDD}.parquet
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化 RAW 存储引擎。

        Args:
            base_dir: RAW 数据根目录，若为 None 则默认从 settings.raw_data_dir 读取。
        """
        self.base_dir = base_dir if base_dir is not None else settings.raw_data_dir

    @staticmethod
    def _dataset_name(data_source: str, endpoint: str) -> str:
        """将项目任务或历史兼容名归一为唯一数据集目录名。"""
        return StorageCompat.canonical_dataset_name(endpoint, data_source)

    def _get_partition_dir(self, data_source: str, endpoint: str, target_date: date) -> Path:
        """根据数据源、项目任务与日期计算 Hive 时间分区目录路径。"""
        endpoint = self._dataset_name(data_source, endpoint)
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.base_dir / data_source / endpoint / year_str / month_str

    def _get_file_path(self, data_source: str, endpoint: str, target_date: date) -> Path:
        """计算 RAW 归档文件路径。"""
        endpoint = self._dataset_name(data_source, endpoint)
        partition_dir = self._get_partition_dir(data_source, endpoint, target_date)
        date_str = target_date.strftime("%Y%m%d")
        return partition_dir / f"{endpoint}_{date_str}.parquet"

    def save_raw(
        self, data_source: str, endpoint: str, target_date: date, df: pl.DataFrame
    ) -> Path:
        """保存原始数据帧到 RAW 离线时间分区目录。

        Args:
            data_source: 数据源标识（如 tushare, akshare）。
            endpoint: 接口名称（如 daily, income）。
            target_date: 目标日期。
            df: 包含原始列的 Polars DataFrame。

        Returns:
            Path: 保存的 Parquet 文件路径。
        """
        if df.is_empty():
            logger.warning(f"数据帧为空，跳过 RAW 保存 [{data_source}/{endpoint}]")
            return self._get_file_path(data_source, endpoint, target_date)

        file_path = self._get_file_path(data_source, endpoint, target_date)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        df.write_parquet(file_path)
        logger.info(
            f"RAW 原始数据归档保存成功 [{data_source}/{endpoint}] -> {file_path} ({len(df)} 条记录)"
        )
        return file_path

    def save_dataset(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        """按数据集和月份幂等合并保存 RAW 归档数据。"""
        date_col = next(
            (c for c in ("trade_date", "date", "end_date", "month", "quarter") if c in df.columns),
            None,
        )
        if date_col and not df.is_empty() and date_col in {"trade_date", "date", "end_date"}:
            # 按真实业务日期分桶，避免请求 end_date 造成历史快照串区。
            raw_str = (
                df.get_column(date_col)
                .cast(pl.Utf8, strict=False)
                .str.replace(r"\.0+$", "")
                .str.replace_all(r"[^\d]", "")
            )
            valid_months_mask = (raw_str.str.len_chars() >= 6) & (
                raw_str.str.slice(0, 4).cast(pl.Int32, strict=False) >= 1990
            ) & (
                raw_str.str.slice(4, 2).cast(pl.Int32, strict=False).is_between(1, 12)
            )
            if valid_months_mask.any():
                month_series = raw_str.str.slice(0, 6)
                months = (
                    month_series.filter(valid_months_mask)
                    .unique()
                    .drop_nulls()
                    .to_list()
                )
                if months:
                    output = self._get_dataset_path(key)
                    for month in months:
                        part = df.filter(month_series == month)
                        y, m = int(month[:4]), int(month[4:6])
                        part_key = DatasetKey(
                            provider=key.provider,
                            dataset=key.dataset,
                            endpoint=key.endpoint,
                            start_date=date(y, m, 1),
                            end_date=date(y, m, 28),
                            instrument=key.instrument,
                            adjustment=key.adjustment,
                            schema_version=key.schema_version,
                        )
                        output = self._save_dataset_file(part_key, part)
                    return output
        return self._save_dataset_file(key, df)

    def _save_dataset_file(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        """保存单个逻辑分区文件。"""
        file_path = self._get_dataset_path(key)
        if df.is_empty():
            return file_path
        if not hasattr(self, "_file_lock"):
            import threading

            self._file_lock = threading.Lock()

        with self._file_lock:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists():
                try:
                    existing = pl.read_parquet(file_path)
                    if not existing.is_empty():
                        df = pl.concat([existing, df], how="diagonal_relaxed")
                        dedup_cols = self._primary_keys(key, df)
                        if dedup_cols:
                            df = df.unique(subset=dedup_cols, keep="last")
                except Exception as e:
                    logger.warning(f"读取合并原有 RAW 文件失败 [{file_path}]: {e}")
            import threading

            temp_path = file_path.with_suffix(f".{threading.get_ident()}.tmp.parquet")
            df.write_parquet(temp_path)
            temp_path.replace(file_path)
            return file_path

    @staticmethod
    def _primary_keys(key: DatasetKey, df: pl.DataFrame) -> list[str]:
        """Resolve registered endpoint keys before falling back to generic identity columns."""
        meta: object | None = None
        try:
            if key.provider == "tushare":
                from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

                meta = TUSHARE_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
            elif key.provider == "lixinger":
                from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

                meta = LIXINGER_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
            else:
                meta = None
            if meta:
                keys = [c for c in meta.primary_keys if c in df.columns]
                if keys:
                    return keys
        except Exception as e:
            logger.debug(f"解析 RAW 主键失败 [{key.provider}/{key.endpoint}]: {e}")
        return [
            c
            for c in ["symbol", "stockCode", "ts_code", "code", "trade_date", "date"]
            if c in df.columns
        ]

    def load_dataset(self, key: DatasetKey) -> pl.DataFrame | None:
        """按数据集和月份读取 RAW 归档数据。"""
        file_path = self._get_dataset_path(key)
        if not file_path.exists():
            return None
        try:
            df = pl.read_parquet(file_path)
            if df.is_empty():
                return None
            symbol = key.instrument_slug
            date_cols = [
                c for c in ["trade_date", "date", "end_date", "month", "quarter"] if c in df.columns
            ]
            if date_cols and any(c in {"trade_date", "date", "end_date"} for c in date_cols):
                date_col = next(c for c in ["trade_date", "date", "end_date"] if c in df.columns)
                values = (
                    df.get_column(date_col).cast(pl.Utf8).str.replace_all("-", "").str.slice(0, 8)
                )
                start = key.start_date.strftime("%Y%m%d")
                end = key.end_date.strftime("%Y%m%d")
                if values.filter((values >= start) & (values <= end)).len() == 0:
                    return None
                min_value = values.min()
                max_value = values.max()
                if (
                    isinstance(min_value, str)
                    and isinstance(max_value, str)
                    and (min_value > start or max_value < end)
                ):
                    return None
            if symbol:
                symbol_col = next(
                    (c for c in ["symbol", "ts_code", "stockCode", "code"] if c in df.columns), None
                )
                if symbol_col:
                    filtered = df.filter(pl.col(symbol_col) == symbol)
                    return filtered if not filtered.is_empty() else None
            return df
        except Exception as e:
            logger.error(f"读取 RAW 请求缓存失败 [{file_path}]: {e}")
            return None

    def _get_dataset_path(self, key: DatasetKey) -> Path:
        """计算 RAW 缓存路径。针对少量/静态/宏观单次数据集，直接存放于数据集根目录。"""
        from stock.data.task_registry import is_task_partitioned

        dataset_name = self._dataset_name(key.provider, key.dataset)
        base_dataset_dir = self.base_dir / key.provider / key.market_slug / dataset_name
        if not is_task_partitioned(key.provider, dataset_name):
            return base_dataset_dir / "data.parquet"

        partition_dir = (
            base_dataset_dir / f"year={key.end_date.year:04d}" / f"month={key.end_date.month:02d}"
        )
        return partition_dir / "data.parquet"

    def load_raw(self, data_source: str, endpoint: str, target_date: date) -> pl.DataFrame | None:
        """读取指定日期的 RAW 归档数据。

        Args:
            data_source: 数据源标识。
            endpoint: 接口名称。
            target_date: 目标日期。

        Returns:
            pl.DataFrame | None: 命中的 RAW 数据帧，若无缓存则返回 None。
        """
        file_path = self._get_file_path(data_source, endpoint, target_date)
        if not file_path.exists():
            return None

        try:
            logger.debug(f"读取 RAW 离线缓存: {file_path}")
            return pl.read_parquet(file_path)
        except Exception as e:
            logger.error(f"读取 RAW 归档文件失败 [{file_path}]: {e}")
            return None

    def has_raw(self, data_source: str, endpoint: str, target_date: date) -> bool:
        """判断本地是否存在指定日期的 RAW 归档数据。"""
        legacy_path = self._get_file_path(data_source, endpoint, target_date)
        if legacy_path.exists():
            return True
        source_dir = self.base_dir / data_source
        if not source_dir.exists():
            return False
        year_month_path = f"year={target_date.year:04d}/month={target_date.month:02d}"
        task = resolve_task(data_source, endpoint)
        dataset_names = [task.dataset]
        market = get_endpoint_market(data_source, task.task_name)
        for dataset_name in dataset_names:
            dataset_dir = source_dir / f"market={market.upper()}" / dataset_name
            path = dataset_dir / year_month_path / "data.parquet"
            if not path.exists() or path.name.endswith((".bak.parquet", ".tmp.parquet")):
                continue
            try:
                df = pl.read_parquet(path)
            except Exception as e:
                logger.warning(f"读取 RAW 日期检查文件失败 [{path}]: {e}")
                continue
            if df.is_empty():
                continue
            date_col = next(
                (c for c in ("trade_date", "date", "end_date") if c in df.columns),
                None,
            )
            if date_col is None:
                return True
            target_plain = target_date.strftime("%Y%m%d")
            candidate_dates = {target_plain}
            effective_date = target_date
            while effective_date.weekday() >= 5:
                effective_date -= timedelta(days=1)
                candidate_dates.add(effective_date.strftime("%Y%m%d"))
            values = (
                df.get_column(date_col)
                .cast(pl.Utf8, strict=False)
                .str.replace_all("-", "")
                .str.replace_all("/", "")
                .str.slice(0, 8)
            )
            if values.filter(values.is_in(candidate_dates)).len() > 0:
                return True
        return False
