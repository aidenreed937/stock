"""ETL 流水线单职责阶段对象 (Pipeline Stages)。"""

from datetime import date, datetime, timezone
from typing import Any
import polars as pl

from stock.core.contracts import (
    DAILY_BAR_CONTRACT,
    DatasetKey,
    InstrumentId,
)
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.normalizer.bar_normalizer import infer_market_exchange_currency
from stock.data.normalizer.base import BaseDataNormalizer
from stock.data.normalizer.unit_normalizer import UnitNormalizer
from stock.data.quality.quarantine import QuarantineStore
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage
from stock.data.task_registry import is_task_partitioned, resolve_task
from stock.exceptions import DataValidationError
from stock.utils.logger import logger


class FetcherStage:
    """提取阶段：负责 RAW 缓存命中检查、数据源拉取、契约校验与 RAW 离线归档。"""

    def __init__(self, fetcher: BaseDataFetcher, raw_store: RawDataStorage, data_source: str) -> None:
        self.fetcher = fetcher
        self.raw_store = raw_store
        self.data_source = data_source

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
    ) -> pl.DataFrame:
        raw_df: pl.DataFrame | None = None
        if use_raw_cache and not force_refresh:
            cached_df = self.raw_store.load_dataset(key)
            if cached_df is not None and not cached_df.is_empty():
                raw_df = cached_df
                logger.info(f"命中 RAW 离线时间分区缓存 [{symbol}]，跳过网络请求")

        if raw_df is None:
            raw_df = self.fetcher.fetch_daily_bars_df(
                symbol, start_date, end_date, endpoint=api_name
            )
            if raw_df.is_empty():
                logger.warning(f"数据源未返回数据 [{symbol}]")
                return raw_df
            raw_df = self.clip_date_range(raw_df, start_date, end_date, endpoint_name)
            self.validate_endpoint_frame(raw_df, start_date, end_date, endpoint_name)
            self.raw_store.save_dataset(key, raw_df)

        raw_df = self.clip_date_range(raw_df, start_date, end_date, endpoint_name)
        self.validate_endpoint_frame(raw_df, start_date, end_date, endpoint_name)
        return raw_df

    def clip_date_range(
        self, frame: pl.DataFrame, start_date: date, end_date: date, endpoint: str
    ) -> pl.DataFrame:
        """按接口业务日期裁剪超出请求范围的记录，豁免免分区/全量/宏观任务。"""
        try:
            task = resolve_task(self.data_source, endpoint)
            if not is_task_partitioned(self.data_source, task.dataset) or task.frequency in (
                "static",
                "event",
            ):
                return frame
        except Exception:
            pass

        date_col = next(
            (c for c in ("trade_date", "date", "end_date", "month", "quarter") if c in frame.columns),
            None,
        )
        if not date_col or frame.is_empty():
            return frame
        values = frame.get_column(date_col).cast(pl.Utf8, strict=False)
        if date_col == "quarter":
            start_val = start_date.year * 4 + ((start_date.month - 1) // 3 + 1)
            end_val = end_date.year * 4 + ((end_date.month - 1) // 3 + 1)
            q_str = pl.col(date_col).cast(pl.Utf8, strict=False).str.to_uppercase()
            yr_expr = q_str.str.extract(r"(\d{4})").cast(pl.Int32, strict=False)
            q_expr = q_str.str.extract(r"Q(\d)").cast(pl.Int32, strict=False)
            q_val = yr_expr * 4 + q_expr
            clipped = frame.filter(q_val.is_between(start_val, end_val))
        elif date_col == "month":
            start_val = start_date.year * 100 + start_date.month
            end_val = end_date.year * 100 + end_date.month
            norm_expr = (
                pl.col(date_col).cast(pl.Utf8, strict=False).str.replace_all("-", "").str.slice(0, 6).cast(pl.Int32, strict=False)
            )
            clipped = frame.filter(norm_expr.is_between(start_val, end_val))
        else:
            start_val = int(start_date.strftime("%Y%m%d"))
            end_val = int(end_date.strftime("%Y%m%d"))
            norm_expr = (
                pl.col(date_col).cast(pl.Utf8, strict=False).str.replace_all("-", "").str.slice(0, 8).cast(pl.Int32, strict=False)
            )
            clipped = frame.filter(norm_expr.is_between(start_val, end_val))
        if len(clipped) != len(frame):
            logger.warning(
                f"接口 [{endpoint}] 丢弃源端请求范围外记录 {len(frame) - len(clipped)} 行 "
                f"(请求范围 {start_date} ~ {end_date}, 日期列 {date_col})"
            )
        return clipped

    def validate_endpoint_frame(
        self, frame: pl.DataFrame, start_date: date, end_date: date, endpoint: str
    ) -> None:
        """按源注册表契约在 RAW 落盘前 fail-closed 校验结构、主键和日期范围。"""
        meta: Any | None = None
        try:
            task = resolve_task(self.data_source, endpoint)
            if self.data_source == "tushare":
                from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

                meta = TUSHARE_API_REGISTRY.get(task.api_name)
            elif self.data_source == "lixinger":
                from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

                meta = LIXINGER_API_REGISTRY.get(task.api_name)
        except Exception:
            meta = None
        if not meta:
            return
        aliases = {"ts_code": "symbol", "stockCode": "symbol"}
        required_columns = getattr(meta, "required_columns", [])
        required = [
            col
            for col in required_columns
            if col not in frame.columns and aliases.get(col) not in frame.columns
        ]
        if required:
            raise DataValidationError(f"接口 [{self.data_source}/{endpoint}] 缺少契约字段: {required}")
        keys = [
            k if k in frame.columns else aliases.get(k, k)
            for k in meta.primary_keys
            if k in frame.columns or aliases.get(k) in frame.columns
        ]
        if keys:
            if any(frame[k].null_count() for k in keys):
                raise DataValidationError(f"接口 [{endpoint}] 主键存在空值: {keys}")
            duplicates = len(frame) - len(frame.unique(subset=keys))
            if duplicates:
                raise DataValidationError(f"接口 [{endpoint}] 主键重复 {duplicates} 行")
        date_col = next((c for c in meta.date_columns if c in frame.columns), None)
        if date_col and meta.max_range_days is not None and start_date and end_date:
            if (end_date - start_date).days > meta.max_range_days:
                raise DataValidationError(
                    f"接口 [{endpoint}] 请求跨度超过契约上限 {meta.max_range_days} 天"
                )


class CleanerStage:
    """清洗阶段：负责单位转换与脏数据清洗/隔离。"""

    def __init__(self, cleaner: BaseDataCleaner, data_source: str) -> None:
        self.cleaner = cleaner
        self.data_source = data_source

    def clean(self, raw_df: pl.DataFrame, api_name: str, dataset: str, request_id: str) -> pl.DataFrame:
        unit_normalizer = UnitNormalizer(self.data_source, api_name)
        unit_df = unit_normalizer.normalize_units(raw_df)

        clean_with_quarantine = getattr(self.cleaner, "clean_with_quarantine", None)
        if callable(clean_with_quarantine):
            from stock.data import pipeline as pipeline_module

            q_cls = getattr(pipeline_module, "QuarantineStore", QuarantineStore)
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

    def __init__(self, normalizer: BaseDataNormalizer, data_source: str) -> None:
        self.normalizer = normalizer
        self.data_source = data_source

    def normalize(
        self,
        cleaned_df: pl.DataFrame,
        instrument: InstrumentId | None,
        api_name: str,
        request_id: str,
    ) -> pl.DataFrame:
        normalized_df = self.normalizer.normalize(cleaned_df)
        if normalized_df.is_empty():
            return normalized_df

        if instrument:
            market_expr = pl.lit(instrument.market)
            exchange_expr = pl.lit(instrument.exchange)
            currency_expr = pl.lit(instrument.currency)
        else:
            if "ts_code" in normalized_df.columns:
                col_ref = pl.col("ts_code")
                market_expr, exchange_expr, currency_expr = infer_market_exchange_currency(
                    col_ref, data_source=self.data_source
                )
            elif "symbol" in normalized_df.columns:
                col_ref = pl.col("symbol")
                market_expr, exchange_expr, currency_expr = infer_market_exchange_currency(
                    col_ref, data_source=self.data_source
                )
            else:
                market_expr = pl.lit("CN" if self.data_source in {"tushare", "lixinger"} else "US")
                exchange_expr = pl.lit("SOURCE")
                currency_expr = pl.lit(
                    "CNY" if self.data_source in {"tushare", "lixinger"} else "USD"
                )

        now_utc = datetime.now(timezone.utc)
        return normalized_df.with_columns(
            [
                pl.lit(self.data_source).alias("data_source"),
                pl.lit(api_name).alias("source_endpoint"),
                pl.lit(request_id).alias("request_id"),
                pl.lit(now_utc).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("updated_at"),
                market_expr.alias("market"),
                exchange_expr.alias("exchange"),
                currency_expr.alias("currency"),
                pl.lit("raw").alias("adjustment"),
                pl.lit("v2").alias("schema_version"),
            ]
        )


class CuratedStorageStage:
    """精炼存储阶段：负责数据集契约校验与 Curated 落盘。"""

    def __init__(self, store: DuckDBMarketStore) -> None:
        self.store = store

    def load(self, key: DatasetKey, df: pl.DataFrame, dataset: str) -> None:
        if dataset in {"stock_daily_bar", "index_daily_bar"}:
            DAILY_BAR_CONTRACT.validate(df)
        self.store.save_dataset(key, df)
