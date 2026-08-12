"""RAW 原始数据离线时间分区归档存储引擎。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.config.settings import settings
from stock.data.contracts import DatasetKey
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

    def _get_partition_dir(
        self, data_source: str, endpoint: str, target_date: date
    ) -> Path:
        """根据数据源、接口名与日期计算 Hive 时间分区目录路径。"""
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.base_dir / data_source / endpoint / year_str / month_str

    def _get_file_path(
        self, data_source: str, endpoint: str, target_date: date
    ) -> Path:
        """计算 RAW 归档文件路径。"""
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
        """按完整请求身份保存 RAW 数据，避免不同请求共享文件。"""
        file_path = self._get_dataset_path(key)
        if df.is_empty():
            return file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_suffix(".tmp.parquet")
        df.write_parquet(temp_path)
        temp_path.replace(file_path)
        return file_path

    def load_dataset(self, key: DatasetKey) -> pl.DataFrame | None:
        """按完整请求身份读取 RAW 数据。"""
        file_path = self._get_dataset_path(key)
        if not file_path.exists():
            return None
        try:
            return pl.read_parquet(file_path)
        except Exception as e:
            logger.error(f"读取 RAW 请求缓存失败 [{file_path}]: {e}")
            return None

    def _get_dataset_path(self, key: DatasetKey) -> Path:
        """计算带请求指纹的 RAW 缓存路径。"""
        partition_dir = self.base_dir / key.provider / key.dataset / f"year={key.end_date.year:04d}" / f"month={key.end_date.month:02d}"
        clean_endpoint = key.endpoint.replace("/", "_")
        filename = f"{clean_endpoint}_{key.instrument_slug}_{key.start_date:%Y%m%d}_{key.end_date:%Y%m%d}_{key.request_id}.parquet"
        return partition_dir / filename

    def load_raw(
        self, data_source: str, endpoint: str, target_date: date
    ) -> pl.DataFrame | None:
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

    def has_raw(
        self, data_source: str, endpoint: str, target_date: date
    ) -> bool:
        """判断本地是否存在指定日期的 RAW 归档数据。"""
        legacy_path = self._get_file_path(data_source, endpoint, target_date)
        if legacy_path.exists():
            return True
        dataset_dir = self.base_dir / data_source / "daily_bar" / f"year={target_date.year:04d}" / f"month={target_date.month:02d}"
        return any(dataset_dir.glob(f"*_{target_date:%Y%m%d}_*.parquet")) if dataset_dir.exists() else False
