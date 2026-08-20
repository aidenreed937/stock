"""领域 Mart 的物理读写能力。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl

from stock_analytics.features.store_ops import merge_incremental, safe_cast_date_col
from stock_core.utils.logger import logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date


class AnalyticsMartStoreMixin:
    """提供分析领域 Mart 的专用读写入口。"""

    mart_dir: Path

    @property
    def industry_daily_path(self) -> Path:
        """申万行业日频宽表 Parquet 物理路径。"""
        return _domain_store(self).domain_mart_path("industry_daily")

    @property
    def industry_panel_daily_path(self) -> Path:
        """申万行业结构面板日频 Mart 物理路径。"""
        return _domain_store(self).domain_mart_path("industry_panel_daily")

    @property
    def market_temperature_derived_facts_path(self) -> Path:
        """市场温度计派生事实 Mart 物理路径。"""
        return _domain_store(self).domain_mart_path("market_temperature_derived_facts")

    def get_industry_daily(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """读取行业日频事实 Mart。"""
        return _domain_store(self).get_domain_mart(
            "industry_daily",
            date_column="trade_date",
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )

    def save_industry_daily(self, df: pl.DataFrame, *, overwrite: bool = False) -> None:
        """保存行业日频事实 Mart。"""
        _domain_store(self).save_domain_mart(
            "industry_daily",
            df,
            keys=["trade_date", "industry_code"],
            date_column="trade_date",
            overwrite=overwrite,
        )

    def get_industry_panel_daily(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """读取行业结构面板日频 Mart。"""
        return _domain_store(self).get_domain_mart(
            "industry_panel_daily",
            date_column="as_of_date",
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )

    def save_industry_panel_daily(self, df: pl.DataFrame, *, overwrite: bool = False) -> None:
        """保存行业结构面板日频 Mart。"""
        _domain_store(self).save_domain_mart(
            "industry_panel_daily",
            df,
            keys=["as_of_date", "industry_code"],
            date_column="as_of_date",
            overwrite=overwrite,
        )

    def get_market_temperature_derived_facts(self, as_of_date: date) -> pl.DataFrame:
        """读取指定基准日的市场温度派生事实快照。"""
        return _domain_store(self).get_domain_mart(
            "market_temperature_derived_facts",
            date_column="as_of_date",
            start_date=as_of_date,
            end_date=as_of_date,
        )

    def save_market_temperature_derived_facts(
        self,
        df: pl.DataFrame,
        *,
        overwrite: bool = False,
    ) -> None:
        """保存市场温度计派生事实快照。"""
        _domain_store(self).save_domain_mart(
            "market_temperature_derived_facts",
            df,
            keys=["as_of_date", "fact_id"],
            date_column="as_of_date",
            overwrite=overwrite,
        )


class DomainMartStoreMixin(AnalyticsMartStoreMixin):
    """为 FeatureStore 提供通用领域 Mart 的读写能力。"""

    mart_dir: Path

    def domain_mart_path(self, mart_name: str) -> Path:
        """返回指定领域宽表的物理路径。"""
        return self.mart_dir / f"{mart_name}.parquet"

    def get_domain_mart(
        self,
        mart_name: str,
        *,
        date_column: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """读取领域宽表，支持日期过滤与列投影。"""
        path = self.domain_mart_path(mart_name)
        if not path.exists():
            return pl.DataFrame()
        try:
            if columns is None:
                df = pl.read_parquet(path)
            else:
                wanted = set(columns)
                if date_column:
                    wanted.add(date_column)
                schema = pl.read_parquet_schema(path)
                df = pl.read_parquet(
                    path, columns=[column for column in schema if column in wanted]
                )
        except Exception as exc:
            logger.error(f"FeatureStore 读取领域 Mart 失败 [{mart_name}]: {exc}")
            return pl.DataFrame()

        if date_column and date_column in df.columns:
            df = safe_cast_date_col(df, date_column)
            if start_date is not None:
                df = df.filter(pl.col(date_column) >= start_date)
            if end_date is not None:
                df = df.filter(pl.col(date_column) <= end_date)
            df = df.sort(date_column)
        if columns is not None:
            df = df.select([column for column in columns if column in df.columns])
        return df

    def save_domain_mart(
        self,
        mart_name: str,
        df: pl.DataFrame,
        *,
        keys: Sequence[str],
        date_column: str | None = None,
        overwrite: bool = False,
    ) -> None:
        """按领域主键原子保存领域宽表。"""
        if df.is_empty():
            return
        if not keys or any(key not in df.columns for key in keys):
            raise ValueError(f"领域 Mart [{mart_name}] 缺少主键列: {keys}")
        save_df = safe_cast_date_col(df, date_column) if date_column else df
        path = self.domain_mart_path(mart_name)
        if path.exists() and not overwrite:
            existing = pl.read_parquet(path)
            existing = safe_cast_date_col(existing, date_column) if date_column else existing
            save_df = merge_incremental(existing, save_df, keys=keys)
        _validate_domain_mart_frame(mart_name, save_df, keys=keys, date_column=date_column)
        sort_columns = [key for key in keys if key in save_df.columns]
        if sort_columns:
            save_df = save_df.sort(sort_columns)

        with tempfile.NamedTemporaryFile(
            dir=self.mart_dir,
            prefix=f"{mart_name}_",
            suffix=".tmp.parquet",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            save_df.write_parquet(tmp_path)
            tmp_path.replace(path)
            logger.info(f"FeatureStore 成功物化领域 Mart [{mart_name}] ({len(save_df)} 行)")
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


def _domain_store(value: object) -> DomainMartStoreMixin:
    """将分析 Mart 入口绑定到同一对象上的通用领域存储实现。"""
    return cast("DomainMartStoreMixin", value)


def _validate_domain_mart_frame(
    mart_name: str,
    frame: pl.DataFrame,
    *,
    keys: Sequence[str],
    date_column: str | None,
) -> None:
    """保存领域 Mart 前执行通用主键、日期和数值门禁。"""
    if frame.is_empty():
        return
    if date_column is not None:
        if date_column not in frame.columns or frame[date_column].dtype != pl.Date:
            raise ValueError(f"领域 Mart [{mart_name}] 日期列不是 pl.Date: {date_column}")
    if any(key not in frame.columns for key in keys):
        raise ValueError(f"领域 Mart [{mart_name}] 缺少主键列: {keys}")
    duplicate_count = frame.height - frame.unique(subset=list(keys)).height
    if duplicate_count:
        raise ValueError(f"领域 Mart [{mart_name}] 存在 {duplicate_count} 条重复主键记录: {keys}")

    float_columns = [
        column for column, dtype in frame.schema.items() if dtype in (pl.Float32, pl.Float64)
    ]
    if float_columns:
        invalid = frame.filter(
            pl.any_horizontal(
                [
                    pl.col(column).is_not_null() & ~pl.col(column).is_finite()
                    for column in float_columns
                ]
            )
        )
        if not invalid.is_empty():
            raise ValueError(f"领域 Mart [{mart_name}] 存在非有限数值")
