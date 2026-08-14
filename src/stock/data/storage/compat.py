"""本地存储引擎历史数据兼容、格式对齐与迁移辅助工具模块。"""

from pathlib import Path
from typing import Any
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

    @staticmethod
    def resolve_dedup_keys(
        dataset_name: str,
        source: str | None,
        data_source: str | None,
        merged: pl.DataFrame,
        bar_datasets: tuple[str, ...] | frozenset[str] | set[str] = (
            "stock_daily_bar",
            "index_daily_bar",
        ),
    ) -> list[str]:
        """根据任务元数据或契约解析去重键，防止宏观或无标的数据集被常量列过度去重。"""
        if dataset_name in bar_datasets:
            return [c for c in ("market", "symbol", "trade_date") if c in merged.columns]

        prov = (source or data_source or "tushare").lower()
        meta_keys: list[str] = []
        try:
            task = resolve_task(prov, dataset_name)
            api_name = task.api_name
            meta: Any = None
            if prov == "tushare":
                from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

                meta = TUSHARE_API_REGISTRY.get(api_name)
            elif prov == "lixinger":
                from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

                meta = LIXINGER_API_REGISTRY.get(api_name)
            if meta and getattr(meta, "primary_keys", None):
                meta_keys = list(meta.primary_keys)
        except Exception:
            pass

        if meta_keys:
            mapped_keys: list[str] = []
            for key in meta_keys:
                if key in ("ts_code", "stockCode", "code") and "symbol" in merged.columns:
                    mapped_keys.append("symbol")
                elif key in ("trade_date", "date", "suspend_date"):
                    if "trade_date" in merged.columns:
                        mapped_keys.append("trade_date")
                    elif "date" in merged.columns:
                        mapped_keys.append("date")
                    elif "suspend_date" in merged.columns:
                        mapped_keys.append("suspend_date")
                elif key in ("end_date", "report_date"):
                    if "end_date" in merged.columns:
                        mapped_keys.append("end_date")
                    elif "report_date" in merged.columns:
                        mapped_keys.append("report_date")
                elif key in merged.columns:
                    mapped_keys.append(key)

            if mapped_keys:
                if "market" in merged.columns and "market" not in mapped_keys:
                    mapped_keys = ["market"] + mapped_keys
                return list(dict.fromkeys(mapped_keys))

        entity_cols = [
            c
            for c in ["symbol", "index_code", "con_code", "stockCode", "ts_code", "code", "exchange_id"]
            if c in merged.columns
        ]
        period_cols = [
            c
            for c in ["trade_date", "date", "month", "quarter", "end_date", "in_date", "out_date", "suspend_date"]
            if c in merged.columns
        ]
        dedup_cols = (["market"] if "market" in merged.columns else []) + entity_cols + period_cols
        return list(dict.fromkeys(dedup_cols)) if (entity_cols or period_cols) else []

    @staticmethod
    def build_dataset_query_clause(
        matched_files: list[str],
        symbol: str | None = None,
        start_date: object | None = None,
        end_date: object | None = None,
    ) -> tuple[list[str], str]:
        """依据 Parquet 文件 Schema 动态构建 SQL 过滤条件与排序列。"""
        conditions: list[str] = []
        order_cols: list[str] = []
        if not matched_files:
            return conditions, ""
        try:
            first_schema = pl.read_parquet_schema(matched_files[0])
            if symbol and "symbol" in first_schema:
                conditions.append(f"symbol = '{symbol}'")
            elif symbol and "ts_code" in first_schema:
                conditions.append(f"ts_code = '{symbol}'")
            if start_date:
                sd_str = f"{start_date:%Y-%m-%d}" if hasattr(start_date, "strftime") else str(start_date)
                if "trade_date" in first_schema:
                    conditions.append(f"trade_date >= '{sd_str}'")
                elif "date" in first_schema:
                    conditions.append(f"date >= '{sd_str}'")
            if end_date:
                ed_str = f"{end_date:%Y-%m-%d}" if hasattr(end_date, "strftime") else str(end_date)
                if "trade_date" in first_schema:
                    conditions.append(f"trade_date <= '{ed_str}'")
                elif "date" in first_schema:
                    conditions.append(f"date <= '{ed_str}'")

            for col in ("trade_date", "date", "month", "quarter"):
                if col in first_schema:
                    order_cols.append(f"{col} ASC")
                    break
            if "symbol" in first_schema:
                order_cols.append("symbol ASC")
        except Exception:
            pass

        order_clause = f" ORDER BY {', '.join(order_cols)}" if order_cols else ""
        return conditions, order_clause
