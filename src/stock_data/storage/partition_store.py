"""底层物理 Parquet 分区目录管理与状态检查 (ParquetPartitionStore)。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from stock_core.contracts import DAILY_BAR_CONTRACT, DatasetKey, validate_dataset_units
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import data_settings
from stock_data.core.task_registry import get_endpoint_market, is_task_partitioned, resolve_task
from stock_data.governance.quality.margin_coverage import (
    is_margin_complete,
    is_margin_date_complete,
    margin_coverage_issues,
)
from stock_data.storage.compat import StorageCompat
from stock_data.storage.partition_writer import ParquetPartitionWriter, validate_frame_source


def _validate_curated_frame(df: pl.DataFrame, source: str, label: str, endpoint: str) -> None:
    validate_frame_source(df, source, label)
    validate_dataset_units(endpoint, df)


def _reject_legacy_schema_version(df: pl.DataFrame, context: str) -> None:
    if "schema_version" not in df.columns or df.is_empty():
        return
    versions = {
        str(v)
        for v in df.get_column("schema_version")
        .cast(pl.Utf8, strict=False)
        .drop_nulls()
        .unique()
        .to_list()
        if str(v)
    }
    invalid = versions - {"v2"}
    if invalid:
        raise DataValidationError(f"{context}包含旧版或未知 schema_version: {sorted(invalid)}")


def _prepare_curated_frame(
    df: pl.DataFrame, endpoint: str, data_source: str | None = None
) -> pl.DataFrame:
    df = _normalize_yfinance_macro_frame(df, data_source, endpoint)
    df = StorageCompat.normalize_dataset_contract_columns(endpoint, df)
    _reject_legacy_schema_version(df, f"Curated 数据集 [{endpoint}] ")
    if "source_endpoint" not in df.columns:
        df = df.with_columns(pl.lit(endpoint).alias("source_endpoint"))
    if "updated_at" not in df.columns:
        df = df.with_columns(
            pl.lit(datetime.now(UTC)).cast(pl.Datetime("us", "UTC")).alias("updated_at")
        )
    if "schema_version" not in df.columns:
        df = df.with_columns(pl.lit("v2").alias("schema_version"))
    return df


def _curated_date_column(data_source: str, dataset: str, df: pl.DataFrame) -> str | None:
    try:
        candidates = tuple(resolve_task(data_source, dataset).date_columns)
    except Exception:
        candidates = ()
    candidates = (*candidates, "trade_date", "ann_date", "date", "report_date", "end_date")
    return next((column for column in dict.fromkeys(candidates) if column in df.columns), None)


def _normalized_date_values(df: pl.DataFrame, date_column: str) -> pl.Series:
    width = 6 if date_column == "month" else 8
    return (
        df.get_column(date_column)
        .cast(pl.Utf8, strict=False)
        .str.replace_all(r"[^0-9]", "")
        .str.slice(0, width)
    )


def _date_matches_expr(date_column: str, target_date: date) -> pl.Expr:
    width = 6 if date_column == "month" else 8
    return pl.col(date_column).cast(pl.Utf8, strict=False).str.replace_all(r"[^0-9]", "").str.slice(
        0, width
    ) == target_date.strftime("%Y%m" if width == 6 else "%Y%m%d")


def _resolve_curated_root(
    storage_dir: Path | str | None, runtime: DataRuntimeContext | None
) -> Path:
    return (
        Path(storage_dir)
        if storage_dir is not None
        else (runtime or data_settings.runtime_context).curated_root
    )


def _resolve_market_code(
    df: pl.DataFrame,
    fallback_market: str,
    data_source: str | None = None,
    endpoint: str = "",
) -> str:
    if data_source in {"alphavantage", "yfinance"} and endpoint in {
        "macro_indicators",
        "fx_daily",
    }:
        return "GLOBAL"
    if "market" in df.columns and not df.is_empty():
        m_values = set(df.get_column("market").drop_nulls().unique().to_list())
        if len(m_values) == 1 and next(iter(m_values)):
            val = next(iter(m_values))
            return str(val) if val is not None else fallback_market
    return fallback_market


def _resolve_source_market_code(df: pl.DataFrame, source: str, endpoint: str) -> str:
    return _resolve_market_code(df, get_endpoint_market(source, endpoint), source, endpoint)


def _normalize_yfinance_macro_frame(
    df: pl.DataFrame, data_source: str | None, endpoint: str
) -> pl.DataFrame:
    """将 yfinance 宏观数据的逻辑市场统一为 GLOBAL。"""
    if (
        data_source not in {"alphavantage", "yfinance"}
        or endpoint
        not in {
            "macro_indicators",
            "fx_daily",
        }
        or df.is_empty()
    ):
        return df

    expressions = [pl.lit("GLOBAL").alias("market")]
    if "exchange" in df.columns:
        expressions.append(pl.lit("GLOBAL").alias("exchange"))
    if "currency" in df.columns:
        expressions.append(pl.lit("USD").alias("currency"))
    return df.with_columns(expressions)


def _active_parquet_paths(storage_dir: Path) -> list[Path]:
    return [p for p in storage_dir.rglob("*.parquet") if not StorageCompat.is_artifact_path(p)]


def _update_curated_cache(
    curated_cache: dict[Path, pl.DataFrame],
    curated_dates_cache: dict[Path, set[str]],
    path: Path,
    df: pl.DataFrame,
) -> None:
    if len(curated_cache) > 128:
        first_key = next(iter(curated_cache))
        del curated_cache[first_key]
    curated_cache[path] = df
    curated_dates_cache.pop(path, None)


class ParquetPartitionStore:
    """负责 Parquet 分区路径、缓存状态检查，并将写入委托给 ParquetPartitionWriter。"""

    def __init__(
        self,
        storage_dir: Path | str | None = None,
        data_source: str | None = None,
        *,
        runtime: DataRuntimeContext | None = None,
    ) -> None:
        self.data_source = data_source
        self._storage_root = _resolve_curated_root(storage_dir, runtime)
        if self.data_source is None and storage_dir is None:
            self.data_source = data_settings.data_source_mode
        self.storage_dir = self._get_source_dir()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.writer = ParquetPartitionWriter(data_source=self.data_source)
        self._curated_cache: dict[Path, pl.DataFrame] = {}
        self._curated_dates_cache: dict[Path, set[str]] = {}

    def _get_source_dir(self) -> Path:
        return self._storage_root / self.data_source if self.data_source else self._storage_root

    def active_parquet_paths(self) -> list[Path]:
        return _active_parquet_paths(self.storage_dir)

    def require_data_source(self) -> str:
        if self.data_source is None:
            raise DataValidationError("Curated 存储未绑定数据源，拒绝读取未隔离目录")
        return self.data_source

    def bind_data_source(self, data_source: str) -> None:
        if self.data_source is None:
            self.data_source = data_source
            self.writer.data_source = data_source
            self.storage_dir = self._get_source_dir()
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        elif self.data_source != data_source:
            raise DataValidationError(
                f"Curated 存储数据源不匹配: 已绑定 [{self.data_source}]，收到 [{data_source}]"
            )

    def enable_batch_mode(self) -> None:
        self.writer.enable_batch_mode()

    def commit(self) -> None:
        self.writer.commit(cache_updater=self._update_cache)

    def _update_cache(self, path: Path, df: pl.DataFrame) -> None:
        _update_curated_cache(self._curated_cache, self._curated_dates_cache, path, df)

    def _merge_and_save_parquet(
        self, file_path: Path, dfs: list[pl.DataFrame], source: str | None = None
    ) -> pl.DataFrame:
        merged = self.writer.merge_and_save_parquet(file_path, dfs, source=source)
        self._update_cache(file_path, merged)
        return merged

    def _dataset_name(self, endpoint: str, data_source: str | None = None) -> str:
        return StorageCompat.canonical_dataset_name(endpoint, data_source or self.data_source)

    def get_parquet_path(self, endpoint: str, target_date: date, market: str = "MULTI") -> Path:
        target_dataset = self._dataset_name(endpoint)
        src = self.data_source or "tushare"
        market_code = get_endpoint_market(src, target_dataset) if market == "MULTI" else market
        if not is_task_partitioned(src, target_dataset):
            return (
                self.storage_dir / f"market={market_code.upper()}" / target_dataset / "data.parquet"
            )
        return (
            self.storage_dir
            / f"market={market_code.upper()}"
            / target_dataset
            / f"year={target_date.year:04d}"
            / f"month={target_date.month:02d}"
            / "data.parquet"
        )

    def has_curated(self, endpoint: str, target_date: date, symbol: str | None = None) -> bool:
        data_source = self.require_data_source()
        target_dataset = self._dataset_name(endpoint)
        year_month_path = f"year={target_date.year:04d}/month={target_date.month:02d}"
        direct_path = self.get_parquet_path(target_dataset, target_date)
        if direct_path.exists() and not StorageCompat.is_artifact_path(direct_path):
            matching_files = [direct_path]
        else:
            matching_files = [
                p
                for p in self.storage_dir.glob(f"**/{target_dataset}/{year_month_path}/*.parquet")
                if not StorageCompat.is_artifact_path(p)
            ]
        if not matching_files:
            return False

        for file_path in matching_files:
            try:
                if file_path not in self._curated_cache:
                    self._curated_cache[file_path] = pl.read_parquet(file_path)
                df = self._curated_cache[file_path]
                if file_path not in self._curated_dates_cache:
                    validate_frame_source(df, data_source, f"Curated 文件 [{file_path}]")
                    date_column = _curated_date_column(data_source, target_dataset, df)
                    if date_column:
                        self._curated_dates_cache[file_path] = set(
                            _normalized_date_values(df, date_column).drop_nulls().unique().to_list()
                        )
                    else:
                        self._curated_dates_cache[file_path] = set()

                dates_str = self._curated_dates_cache[file_path]
                date_column = _curated_date_column(data_source, target_dataset, df)
                date_key = target_date.strftime("%Y%m" if date_column == "month" else "%Y%m%d")
                if not date_column or date_key in dates_str:
                    df = self._curated_cache[file_path]
                    day_df = (
                        df.filter(_date_matches_expr(date_column, target_date))
                        if date_column
                        else df
                    )
                    if (
                        data_source == "tushare"
                        and target_dataset == "margin"
                        and not is_margin_date_complete(day_df, target_date)
                    ):
                        continue
                    if symbol:
                        if "symbol" not in day_df.columns:
                            continue
                        matched = day_df.filter(
                            pl.col("symbol").cast(pl.Utf8, strict=False) == str(symbol)
                        )
                        if matched.is_empty():
                            continue
                    elif not symbol and "stock_daily_bar" in str(file_path):
                        if "symbol" in day_df.columns:
                            min_symbols = (
                                5
                                if target_date.year < 1993
                                else 50
                                if target_date.year < 1996
                                else 300
                                if target_date.year < 2000
                                else 800
                            )
                            if len(day_df["symbol"].unique()) < min_symbols:
                                continue
                    return True

            except Exception as e:
                logger.warning(f"忽略无效 Curated 缓存 [{file_path}]: {e}")
                continue
        return False

    def save_curated(
        self, df: pl.DataFrame, endpoint: str, target_date: date, data_source: str | None = None
    ) -> Path:
        source = data_source or self.data_source
        if source is None and "data_source" in df.columns:
            sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
            if len(sources) == 1:
                source = next(iter(sources))
        if source is None:
            raise DataValidationError("Curated 数据缺少数据源，拒绝写入未绑定来源的数据")
        self.bind_data_source(source)
        endpoint = self._dataset_name(endpoint, source)
        market_code = _resolve_source_market_code(df, source, endpoint)

        if df.is_empty():
            return self.get_parquet_path(endpoint, target_date, market=market_code)

        file_path = self.get_parquet_path(endpoint, target_date, market=market_code)
        df = _prepare_curated_frame(df, endpoint, source)
        if (
            source == "tushare"
            and endpoint == "margin"
            and not is_margin_complete(df, start_date=target_date, end_date=target_date)
        ):
            issues = margin_coverage_issues(df, start_date=target_date, end_date=target_date)
            raise DataValidationError(
                f"Curated 数据集 [margin] 交易所覆盖不完整: {'; '.join(issues)}"
            )
        _validate_curated_frame(df, source, f"Curated 数据 [{file_path}]", endpoint)
        if endpoint in {"daily_bar", "stock_daily_bar", "index_daily_bar", "fund_daily"}:
            DAILY_BAR_CONTRACT.validate(df)

        return self.writer.save_partitioned(
            df=df,
            dataset_name=endpoint,
            fallback_date=target_date,
            market_code=market_code,
            source=source,
            storage_dir=self.storage_dir,
            path_resolver=self.get_parquet_path,
            cache_updater=self._update_cache,
        )

    def save_dataset(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        self.bind_data_source(key.provider)
        dataset_name = self._dataset_name(key.dataset, key.provider)
        fallback_market = (
            key.instrument.market
            if key.instrument and key.instrument.market
            else get_endpoint_market(key.provider, dataset_name)
        )
        market_code = _resolve_market_code(df, fallback_market, key.provider, dataset_name)
        file_path = self.get_parquet_path(dataset_name, key.end_date, market=market_code)
        if df.is_empty():
            return file_path

        df = _prepare_curated_frame(df, key.endpoint, key.provider)
        if (
            key.provider == "tushare"
            and dataset_name == "margin"
            and not is_margin_complete(df, start_date=key.start_date, end_date=key.end_date)
        ):
            issues = margin_coverage_issues(df, start_date=key.start_date, end_date=key.end_date)
            raise DataValidationError(
                f"Curated 数据集 [margin] 交易所覆盖不完整: {'; '.join(issues)}"
            )
        _validate_curated_frame(df, key.provider, f"Curated 数据 [{file_path}]", dataset_name)
        if dataset_name in {"daily_bar", "stock_daily_bar", "index_daily_bar", "fund_daily"}:
            DAILY_BAR_CONTRACT.validate(df)

        return self.writer.save_partitioned(
            df=df,
            dataset_name=dataset_name,
            fallback_date=key.end_date,
            market_code=market_code,
            source=key.provider,
            storage_dir=self.storage_dir,
            path_resolver=self.get_parquet_path,
            cache_updater=self._update_cache,
        )
