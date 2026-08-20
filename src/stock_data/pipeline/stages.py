"""ETL 流水线单职责阶段对象 (Pipeline Stages)。"""

from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from stock_core.contracts import (
    DAILY_BAR_CONTRACT,
    DatasetKey,
    InstrumentId,
)
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.task_registry import _provider_registry, resolve_task
from stock_data.fetcher.base import BaseDataFetcher
from stock_data.governance.quality.margin_coverage import is_margin_complete, margin_coverage_issues
from stock_data.governance.quality.margin_quality import (
    margin_quality_issues,
    margin_quality_report,
)
from stock_data.governance.quality.quarantine import QuarantineStore
from stock_data.pipeline.cleaner.base import BaseDataCleaner
from stock_data.pipeline.date_clipper import clip_endpoint_date_range
from stock_data.pipeline.normalizer.bar_normalizer import (
    infer_metadata_expressions,
    normalize_stock_daily_bar_curated_schema,
)
from stock_data.pipeline.normalizer.base import BaseDataNormalizer
from stock_data.pipeline.normalizer.sw_daily_enricher import (
    enrich_sw_daily_frame,
    normalize_sw_daily_identity,
)
from stock_data.pipeline.normalizer.unit_normalizer import UnitNormalizer
from stock_data.storage.compat import StorageCompat
from stock_data.storage.duckdb_store import DuckDBMarketStore
from stock_data.storage.raw_schema import RAW_DATE_CANDIDATE_COLUMNS, normalize_raw_date_series
from stock_data.storage.raw_store import RawDataStorage

_VALIDATION_COLUMN_ALIASES = {
    "ts_code": "symbol",
    "stockCode": "symbol",
    "date": "trade_date",
    "as_of_date": "asOfDate",
    "endDate": "trade_date",
}


class FetcherStage:
    """提取阶段：负责 RAW 缓存命中检查、数据源拉取、契约校验与 RAW 离线归档。"""

    def __init__(
        self,
        fetcher: BaseDataFetcher,
        raw_store: RawDataStorage,
        data_source: str,
        quarantine: QuarantineStore | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.raw_store = raw_store
        self.data_source = data_source
        self.quarantine = quarantine or QuarantineStore()

    def extract(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        key: DatasetKey,
        api_name: str,
        endpoint_name: str,
        use_raw_cache: bool = True,
        force_refresh: bool = False,
        max_workers: int = 1,
    ) -> pl.DataFrame:
        raw_df: pl.DataFrame | None = None
        batch_df: pl.DataFrame | None = None
        force_raw_replace = False
        if use_raw_cache and not force_refresh:
            cached_df = self.raw_store.load_dataset(key)
            if cached_df is not None and not cached_df.is_empty():
                try:
                    self.validate_endpoint_frame(cached_df, start_date, end_date, endpoint_name)
                except DataValidationError as exc:
                    logger.warning(
                        f"RAW 缓存契约不兼容 [{symbol}/{endpoint_name}]，重新抓取: {exc}"
                    )
                    force_raw_replace = True
                else:
                    raw_df = cached_df
                    logger.info(f"命中 RAW 离线时间分区缓存 [{symbol}]，跳过网络请求")

        if raw_df is None:
            try:
                fetch_kwargs: dict[str, Any] = {
                    "endpoint": api_name,
                    "endpoint_name": endpoint_name,
                }
                if max_workers > 1:
                    fetch_kwargs["max_workers"] = max_workers
                raw_df = self.fetcher.fetch_daily_bars_df(
                    symbol, start_date, end_date, **fetch_kwargs
                )
            except TypeError:
                fetch_kwargs.pop("endpoint_name", None)
                try:
                    raw_df = self.fetcher.fetch_daily_bars_df(
                        symbol, start_date, end_date, **fetch_kwargs
                    )
                except TypeError:
                    fetch_kwargs.pop("max_workers", None)
                    raw_df = self.fetcher.fetch_daily_bars_df(
                        symbol, start_date, end_date, **fetch_kwargs
                    )
            if raw_df.is_empty():
                logger.warning(f"数据源未返回数据 [{symbol}]")
                return raw_df
            batch_df = raw_df
            if force_raw_replace:
                self.raw_store.save_dataset(key, raw_df, replace_existing=True)
            else:
                self.raw_store.save_dataset(key, raw_df)

        raw_df = self.clip_date_range(raw_df, start_date, end_date, endpoint_name)
        try:
            self.validate_endpoint_frame(raw_df, start_date, end_date, endpoint_name)
        except DataValidationError as err:
            self.quarantine.write(
                batch_df if batch_df is not None else raw_df,
                endpoint=endpoint_name,
                reason=f"endpoint_validation_failed: {err}",
                request_id=key.request_id,
                data_source=self.data_source,
            )
            raise

        if raw_df.is_empty():
            return raw_df

        if endpoint_name == "margin":
            issues = margin_coverage_issues(raw_df, start_date=start_date, end_date=end_date)
            if issues:
                self.quarantine.write(
                    batch_df if batch_df is not None else raw_df,
                    endpoint=endpoint_name,
                    reason=f"incomplete_exchange_coverage: {'; '.join(issues)}",
                    request_id=key.request_id,
                    data_source=self.data_source,
                )
                issue_text = "; ".join(issues)
                raise DataValidationError(
                    f"接口 [{self.data_source}/{endpoint_name}] 交易所覆盖不完整: {issue_text}"
                )
            quality_report = margin_quality_report(raw_df)
            if quality_report.errors:
                self.quarantine.write(
                    batch_df if batch_df is not None else raw_df,
                    endpoint=endpoint_name,
                    reason=f"margin_value_quality_failed: {'; '.join(quality_report.errors)}",
                    request_id=key.request_id,
                    data_source=self.data_source,
                )
                raise DataValidationError(
                    f"接口 [{self.data_source}/{endpoint_name}] 数值质量不合格: "
                    f"{'; '.join(quality_report.errors)}"
                )
            for warning in quality_report.warnings:
                logger.warning(f"接口 [{self.data_source}/{endpoint_name}] 数值质量告警: {warning}")
        return raw_df

    def clip_date_range(
        self, frame: pl.DataFrame, start_date: date, end_date: date, endpoint: str
    ) -> pl.DataFrame:
        """按接口业务日期裁剪超出请求范围的记录。"""
        return clip_endpoint_date_range(frame, start_date, end_date, endpoint, self.data_source)

    def validate_endpoint_frame(
        self, frame: pl.DataFrame, start_date: date, end_date: date, endpoint: str
    ) -> None:
        """按源注册表契约在 RAW 落盘前 fail-closed 校验结构、主键和日期范围。"""
        meta: Any | None = None
        try:
            task = resolve_task(self.data_source, endpoint)
            meta = _provider_registry(self.data_source).get(task.api_name)
        except Exception:
            meta = None
        if not meta:
            return
        required_columns = getattr(meta, "required_columns", [])
        required = [
            col
            for col in required_columns
            if col not in frame.columns and _VALIDATION_COLUMN_ALIASES.get(col) not in frame.columns
        ]
        if required:
            raise DataValidationError(
                f"接口 [{self.data_source}/{endpoint}] 缺少契约字段: {required}"
            )
        keys = [
            k if k in frame.columns else _VALIDATION_COLUMN_ALIASES.get(k, k)
            for k in meta.primary_keys
            if k in frame.columns or _VALIDATION_COLUMN_ALIASES.get(k) in frame.columns
        ]
        if keys:
            validation_frame = frame
            validation_keys: list[str] = []
            for key in keys:
                if key in RAW_DATE_CANDIDATE_COLUMNS:
                    normalized_key = f"_normalized_pk_{key}"
                    validation_frame = validation_frame.with_columns(
                        normalize_raw_date_series(pl.col(key)).alias(normalized_key)
                    )
                    validation_keys.append(normalized_key)
                else:
                    validation_keys.append(key)

            nullable_keys = set(getattr(meta, "nullable_primary_keys", []))
            required_validation_keys = [
                validation_key
                for source_key, validation_key in zip(keys, validation_keys, strict=True)
                if source_key not in nullable_keys and validation_key not in nullable_keys
            ]
            if any(validation_frame[k].null_count() for k in required_validation_keys):
                raise DataValidationError(f"接口 [{endpoint}] 主键存在空值: {keys}")
            duplicates = len(validation_frame) - len(
                validation_frame.unique(subset=validation_keys)
            )
            if duplicates:
                raise DataValidationError(f"接口 [{endpoint}] 主键重复 {duplicates} 行")
        date_col = next((c for c in meta.date_columns if c in frame.columns), None)
        if date_col and meta.max_range_days is not None and start_date and end_date:
            if (end_date - start_date).days > meta.max_range_days:
                logger.debug(
                    f"接口 [{endpoint}] 回填跨度 {(end_date - start_date).days} 天已由 Fetcher 自动分段拉取合并"
                )


class CleanerStage:
    """清洗阶段：负责单位转换与脏数据清洗/隔离。"""

    def __init__(self, cleaner: BaseDataCleaner, data_source: str) -> None:
        self.cleaner, self.data_source = cleaner, data_source

    def clean(
        self, raw_df: pl.DataFrame, api_name: str, dataset: str, request_id: str
    ) -> pl.DataFrame:
        if self.data_source == "tushare" and dataset == "sw_daily":
            raw_df = normalize_sw_daily_identity(raw_df)
        unit_normalizer = UnitNormalizer(self.data_source, api_name)
        unit_df, unit_rejected = unit_normalizer.normalize_units_with_quarantine(raw_df)

        clean_with_quarantine = getattr(self.cleaner, "clean_with_quarantine", None)
        if callable(clean_with_quarantine):
            from stock_data import pipeline as pipeline_module

            q_cls = getattr(pipeline_module, "QuarantineStore", QuarantineStore)
            if not unit_rejected.is_empty():
                q_cls().write(
                    unit_rejected,
                    endpoint=dataset,
                    reason="unit_inference_failed",
                    request_id=request_id,
                    data_source=self.data_source,
                )
            res = clean_with_quarantine(
                unit_df,
                endpoint=dataset,
                request_id=request_id,
                data_source=self.data_source,
                quarantine=q_cls(),
            )
            return res if isinstance(res, pl.DataFrame) else pl.DataFrame(res)
        res = self.cleaner.clean(unit_df)
        return res if isinstance(res, pl.DataFrame) else pl.DataFrame(res)


class NormalizerStage:
    """标准化与血统注入阶段：列名映射、类型转换与数据血统注入。"""

    def __init__(
        self,
        normalizer: BaseDataNormalizer,
        data_source: str,
        sw_daily_classification: pl.DataFrame | None = None,
    ) -> None:
        self.normalizer, self.data_source = normalizer, data_source
        self.sw_daily_classification = sw_daily_classification

    def normalize(
        self,
        cleaned_df: pl.DataFrame,
        instrument: InstrumentId | None,
        api_name: str,
        request_id: str,
        dataset: str | None = None,
    ) -> pl.DataFrame:
        normalized_df = self.normalizer.normalize(cleaned_df)
        if normalized_df.is_empty():
            return normalized_df
        normalized_df = StorageCompat.ensure_dataset_identity(dataset or api_name, normalized_df)

        market_expr, exchange_expr, currency_expr = infer_metadata_expressions(
            normalized_df, instrument, self.data_source, api_name, dataset
        )

        now_utc = datetime.now(UTC)
        source_endpoint = dataset or api_name
        decorated = normalized_df.with_columns(
            [
                pl.lit(self.data_source).alias("data_source"),
                pl.lit(source_endpoint).alias("source_endpoint"),
                pl.lit(request_id).alias("request_id"),
                pl.lit(now_utc)
                .cast(pl.Datetime(time_unit="us", time_zone="UTC"))
                .alias("updated_at"),
                market_expr.alias("market"),
                exchange_expr.alias("exchange"),
                currency_expr.alias("currency"),
                pl.lit("raw").alias("adjustment"),
                pl.lit("v2").alias("schema_version"),
            ]
        )
        if self.data_source == "tushare" and dataset == "sw_daily":
            decorated = enrich_sw_daily_frame(decorated, self.sw_daily_classification)
        if self.data_source == "tushare" and dataset == "stock_daily_bar":
            return normalize_stock_daily_bar_curated_schema(decorated)
        return decorated


class CuratedStorageStage:
    """精炼存储阶段：负责数据集契约校验与 Curated 落盘。"""

    def __init__(self, store: DuckDBMarketStore) -> None:
        self.store = store

    def load(self, key: DatasetKey, df: pl.DataFrame, dataset: str) -> None:
        if dataset in {"stock_daily_bar", "index_daily_bar"}:
            DAILY_BAR_CONTRACT.validate(df)
        if dataset == "margin" and not is_margin_complete(
            df, start_date=key.start_date, end_date=key.end_date
        ):
            issues = margin_coverage_issues(df, start_date=key.start_date, end_date=key.end_date)
            raise DataValidationError(
                f"Curated 数据集 [margin] 交易所覆盖不完整: {'; '.join(issues)}"
            )
        if dataset == "margin":
            quality_issues = margin_quality_issues(df)
            if quality_issues:
                raise DataValidationError(
                    f"Curated 数据集 [margin] 数值质量不合格: {'; '.join(quality_issues)}"
                )
        self.store.save_dataset(key, df)
