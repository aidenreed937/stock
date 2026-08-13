"""本地存储引擎历史数据兼容、格式对齐与迁移辅助工具模块。"""

from pathlib import Path
import polars as pl

from stock.data.task_registry import resolve_task


class StorageCompat:
    """集中管理存量数据兼容、格式归一与历史迁移辅助逻辑。"""

    @staticmethod
    def is_artifact_path(path: Path) -> bool:
        """跳过迁移备份、临时快照等非有效 Parquet 文件。"""
        return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))

    @staticmethod
    def canonical_dataset_name(endpoint: str, provider: str | None = None) -> str:
        """将历史兼容参数解析为唯一项目任务/数据集目录名。"""
        if provider is not None:
            try:
                return resolve_task(provider, endpoint).dataset
            except ValueError:
                pass
        if endpoint in {"daily", "daily_bar", "history"}:
            return "stock_daily_bar"
        return endpoint

    @staticmethod
    def normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
        """将历史/源端标的与日期别名 (ts_code, stockCode, code, date) 归一为 Curated 标准列。"""
        normalized = df
        for alias in ("ts_code", "stockCode"):
            if alias not in normalized.columns:
                continue
            if "symbol" not in normalized.columns:
                normalized = normalized.rename({alias: "symbol"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col(alias).cast(pl.Utf8, strict=False),
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop(alias)
        if "code" in normalized.columns:
            if "symbol" not in normalized.columns:
                normalized = normalized.rename({"code": "symbol"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                            pl.col("code").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop("code")
        if "date" in normalized.columns:
            if "trade_date" not in normalized.columns:
                normalized = normalized.rename({"date": "trade_date"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("trade_date").cast(pl.Utf8, strict=False),
                            pl.col("date").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("trade_date")
                ).drop("date")
        return normalized

    @staticmethod
    def normalize_datetime_columns(df: pl.DataFrame) -> pl.DataFrame:
        """将合并中的 datetime 列统一为 UTC 微秒精度。"""
        target_dtype = pl.Datetime(time_unit="us", time_zone="UTC")
        expressions = []
        for column, dtype in df.schema.items():
            if not isinstance(dtype, pl.Datetime):
                continue
            expression = pl.col(column)
            if dtype.time_zone is None:
                expression = expression.dt.replace_time_zone("UTC")
            else:
                expression = expression.dt.convert_time_zone("UTC")
            expressions.append(expression.cast(target_dtype).alias(column))
        return df.with_columns(expressions) if expressions else df
