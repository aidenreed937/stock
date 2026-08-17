"""Analytics Mart 领域宽表与 Feature 物理存储层 (FeatureStore)。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.features.feature_values import FeatureValueStore
from stock_analytics.features.store_ops import (
    merge_incremental,
    read_metadata,
    validate_incremental_metadata,
    write_metadata,
)
from stock_core.config.settings import settings
from stock_core.utils.logger import logger
from stock_data.storage.compat import StorageCompat

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date


class FeatureStore:
    """提供全市场/行业领域宽表与特征的高性能读写。"""

    def __init__(self, mart_dir: Path | str | None = None) -> None:
        """初始化 FeatureStore。"""
        if mart_dir is not None:
            self.mart_dir = Path(mart_dir)
        else:
            self.mart_dir = settings.curated_data_dir / "mart"
        self.mart_dir.mkdir(parents=True, exist_ok=True)
        self.values = FeatureValueStore(self.mart_dir)

    @property
    def market_daily_path(self) -> Path:
        """全市场日频宽表 Parquet 物理路径。"""
        return self.mart_dir / "market_daily.parquet"

    @property
    def industry_daily_path(self) -> Path:
        """申万行业日频宽表 Parquet 物理路径。"""
        return self.mart_dir / "industry_daily.parquet"

    def get_market_daily(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """读取全市场日频物化宽表。

        支持列投影与起止日期过滤。
        """
        path = self.market_daily_path
        if not path.exists():
            return pl.DataFrame()

        try:
            if columns is not None:
                wanted = set(columns)
                wanted.add("trade_date")
                file_schema = pl.read_parquet_schema(path)
                read_cols = [c for c in file_schema if c in wanted]
                df = pl.read_parquet(path, columns=read_cols)
            else:
                df = pl.read_parquet(path)
        except Exception as e:
            logger.error(f"FeatureStore 读取 market_daily 失败: {e}")
            return pl.DataFrame()

        if df.is_empty():
            return df

        if "trade_date" in df.columns:
            df = StorageCompat.safe_cast_date_col(df, "trade_date")
            if start_date is not None:
                df = df.filter(pl.col("trade_date") >= start_date)
            if end_date is not None:
                df = df.filter(pl.col("trade_date") <= end_date)
            df = df.sort("trade_date")

        if columns is not None and not df.is_empty():
            selected = [c for c in columns if c in df.columns]
            df = df.select(selected)

        return df

    def get_market_daily_metadata(self) -> dict[str, Any]:
        """读取 market_daily 的定义版本、输入水位和构建指纹。"""
        return read_metadata(self.mart_dir)

    def save_market_daily(
        self,
        df: pl.DataFrame,
        *,
        overwrite: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """原子持久化全市场日频宽表。"""
        if df.is_empty():
            return

        target_path = self.market_daily_path
        save_df = df
        if "trade_date" in save_df.columns:
            save_df = StorageCompat.safe_cast_date_col(save_df, "trade_date")

        if target_path.exists() and not overwrite:
            validate_incremental_metadata(self.mart_dir, metadata)
            existing = pl.read_parquet(target_path)
            existing = StorageCompat.safe_cast_date_col(existing, "trade_date")
            save_df = merge_incremental(existing, save_df, keys=["trade_date"])

        if "trade_date" in save_df.columns:
            save_df = save_df.sort("trade_date")

        # 原子写入：先写入同目录临时文件，再原子替换
        with tempfile.NamedTemporaryFile(
            dir=self.mart_dir,
            prefix="market_daily_",
            suffix=".tmp.parquet",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        try:
            save_df.write_parquet(tmp_path)
            tmp_path.replace(target_path)
            logger.info(f"FeatureStore 成功物化 market_daily ({len(save_df)} 行) -> {target_path}")
            if metadata is not None:
                write_metadata(self.mart_dir, metadata)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def get_latest_market_daily_date(self) -> date | None:
        """获取已物化 market_daily 的最新交易日。"""
        path = self.market_daily_path
        if not path.exists():
            return None
        try:
            df = pl.read_parquet(path, columns=["trade_date"])
            if df.is_empty():
                return None
            df = StorageCompat.safe_cast_date_col(df, "trade_date")
            dates = df["trade_date"].drop_nulls().to_list()
            return max(dates) if dates else None
        except Exception:
            return None
