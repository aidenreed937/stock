"""行情数据同步与 2-Tier ETL Pipeline 编排管道 (MarketDataPipeline)。"""

from datetime import date

import polars as pl

from stock_core.contracts import DatasetKey, instrument_for_symbol
from stock_core.utils.logger import logger
from stock_data.cleaner.bar_cleaner import BarDataCleaner
from stock_data.cleaner.base import BaseDataCleaner
from stock_data.cleaner.generic_cleaner import GenericCleaner
from stock_data.cleaner.macro_cleaner import MacroDataCleaner
from stock_data.fetcher.base import BaseDataFetcher
from stock_data.normalizer.bar_normalizer import BarDataNormalizer
from stock_data.normalizer.base import BaseDataNormalizer
from stock_data.normalizer.generic_normalizer import GenericNormalizer
from stock_data.pipeline_stages import (
    CleanerStage,
    CuratedStorageStage,
    FetcherStage,
    NormalizerStage,
)
from stock_data.storage.duckdb_store import DuckDBMarketStore
from stock_data.storage.raw_store import RawDataStorage
from stock_data.task_registry import resolve_task


class MarketDataPipeline:
    """行情数据 ETL 处理管道 (包含 RAW 离线时间分区归档与 Curated 标准化精炼)。

    编排流程:
    1. Extract (FetcherStage): 检查 RAW 离线缓存，未命中时向 Fetcher 抓取、裁剪、校验并保存 RAW。
    2. Clean (CleanerStage): 显式单位对齐，并执行合规清洗与 Quarantine 隔离。
    3. Normalize (NormalizerStage): 字段标准化与数据血统 (Lineage) 注入。
    4. Load (CuratedStorageStage): 校验业务契约并落盘至 Curated 存储。
    """

    def __init__(
        self,
        fetcher: BaseDataFetcher,
        cleaner: BaseDataCleaner | None = None,
        normalizer: BaseDataNormalizer | None = None,
        store: DuckDBMarketStore | None = None,
        raw_store: RawDataStorage | None = None,
        data_source: str = "tushare",
        endpoint: str = "stock_daily_bar",
    ) -> None:
        self.fetcher = fetcher
        self.data_source = data_source
        self.endpoint = resolve_task(data_source, endpoint).task_name

        profile = self._endpoint_quality_profile(data_source, self.endpoint)
        if cleaner is not None:
            self.cleaner = cleaner
        elif profile == "bar":
            self.cleaner = BarDataCleaner(
                listing_dates=BarDataCleaner.load_listing_dates(data_source)
            )
        elif profile == "macro":
            self.cleaner = MacroDataCleaner()
        else:
            self.cleaner = GenericCleaner()

        self.normalizer = (
            normalizer
            if normalizer is not None
            else (BarDataNormalizer() if profile == "bar" else GenericNormalizer())
        )
        self.store = store if store is not None else DuckDBMarketStore(data_source=data_source)
        bind_data_source = getattr(self.store, "bind_data_source", None)
        if callable(bind_data_source):
            bind_data_source(data_source)
        self.raw_store = raw_store if raw_store is not None else RawDataStorage()

        # 初始化单职责流水线阶段
        self.fetcher_stage = FetcherStage(self.fetcher, self.raw_store, self.data_source)
        self.cleaner_stage = CleanerStage(self.cleaner, self.data_source)
        self.normalizer_stage = NormalizerStage(self.normalizer, self.data_source)
        self.storage_stage = CuratedStorageStage(self.store)

    @staticmethod
    def _endpoint_quality_profile(data_source: str, endpoint: str) -> str:
        return resolve_task(data_source, endpoint).quality_profile

    def _get_fetcher_stage(self) -> FetcherStage:
        stage = getattr(self, "fetcher_stage", None)
        if stage is None:
            stage = FetcherStage(
                fetcher=getattr(self, "fetcher", None),  # type: ignore
                raw_store=getattr(self, "raw_store", None),  # type: ignore
                data_source=getattr(self, "data_source", "tushare"),
            )
            self.fetcher_stage = stage
        return stage

    def _clip_endpoint_date_range(
        self, frame: pl.DataFrame, start_date: date, end_date: date
    ) -> pl.DataFrame:
        endpoint = getattr(self, "endpoint", "stock_daily_bar")
        return self._get_fetcher_stage().clip_date_range(frame, start_date, end_date, endpoint)

    def _validate_endpoint_frame(
        self, frame: pl.DataFrame, start_date: date, end_date: date
    ) -> None:
        endpoint = getattr(self, "endpoint", "stock_daily_bar")
        self._get_fetcher_stage().validate_endpoint_frame(frame, start_date, end_date, endpoint)

    def sync_daily_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        use_raw_cache: bool = True,
        force_refresh: bool = False,
    ) -> pl.DataFrame:
        """执行两层 ETL 流程同步指定标的数据。"""
        logger.info(f"开始 2-Tier ETL 管道同步 [{symbol}] (范围: {start_date} ~ {end_date})...")

        task = resolve_task(self.data_source, self.endpoint, symbol=symbol)
        dataset = task.dataset
        instrument = (
            None if symbol == self.endpoint else instrument_for_symbol(symbol, self.data_source)
        )
        key = DatasetKey(
            provider=self.data_source,
            dataset=dataset,
            endpoint=task.task_name,
            start_date=start_date,
            end_date=end_date,
            instrument=instrument,
        )

        # 1. 提取 (Extract / Fetch)
        raw_df = self.fetcher_stage.extract(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            key=key,
            api_name=task.api_name,
            endpoint_name=self.endpoint,
            use_raw_cache=use_raw_cache,
            force_refresh=force_refresh,
        )
        if raw_df.is_empty():
            return raw_df

        # 2. 清洗 (Clean & Normalize Units)
        cleaned_df = self.cleaner_stage.clean(
            raw_df=raw_df, api_name=task.api_name, dataset=dataset, request_id=key.request_id
        )

        # 3. 标准化与血统注入 (Normalize & Lineage)
        normalized_df = self.normalizer_stage.normalize(
            cleaned_df=cleaned_df,
            instrument=instrument,
            api_name=task.api_name,
            request_id=key.request_id,
            dataset=dataset,
        )

        # 4. 精炼落盘 (Load to Curated Store)
        self.storage_stage.load(key=key, df=normalized_df, dataset=dataset)

        logger.info(
            f"2-Tier ETL 管道同步成功完成 [{symbol}] -> 精炼落盘 {len(normalized_df)} 条记录"
        )
        return normalized_df
