"""行情数据同步与 2-Tier ETL Pipeline 编排管道。"""

from datetime import date, datetime

import polars as pl

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.contracts import (
    DAILY_BAR_CONTRACT,
    DatasetKey,
    dataset_for_endpoint,
    instrument_for_symbol,
)
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.normalizer.bar_normalizer import (
    BarDataNormalizer,
    infer_market_exchange_currency,
)
from stock.data.normalizer.base import BaseDataNormalizer
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage
from stock.utils.logger import logger


class MarketDataPipeline:
    """行情数据 ETL 处理管道 (包含 RAW 离线时间分区归档与 Curated 标准化精炼)。

    编排流程:
    1. Extract / RAW Cache Check: 检查 RAW 时间分区离线缓存。未命中时从 Fetcher 读取。
    2. Save RAW Archive: 自动归档保存原始响应至 data/raw/{source}/{endpoint}/year=YYYY/month=MM/。
    3. Clean (清洗): 过滤非法价格与重复项。
    4. Normalize & Lineage (标准化与血统注入): 列名映射、对齐数据类型并附加 data_source 与 updated_at。
    5. Load (精炼落盘): 使用 Curated Store 写入 DuckDB / Parquet 存储。
    """

    def __init__(
        self,
        fetcher: BaseDataFetcher,
        cleaner: BaseDataCleaner | None = None,
        normalizer: BaseDataNormalizer | None = None,
        store: DuckDBMarketStore | None = None,
        raw_store: RawDataStorage | None = None,
        data_source: str = "tushare",
        endpoint: str = "daily",
    ):
        """初始化行情 ETL 管道。

        Args:
            fetcher: 数据抓取器。
            cleaner: 数据清洗器，默认根据 endpoint 动态匹配。
            normalizer: 数据标准化器，默认 BarDataNormalizer。
            store: 精炼存储引擎，默认 DuckDBMarketStore。
            raw_store: 原始归档存储引擎，默认 RawDataStorage。
            data_source: 数据源标识名称（如 tushare, akshare）。
            endpoint: 接口名称（如 daily, income）。
        """
        self.fetcher = fetcher
        self.data_source = data_source
        self.endpoint = endpoint

        if cleaner is not None:
            self.cleaner = cleaner
        elif endpoint == "daily":
            self.cleaner = BarDataCleaner()
        else:
            self.cleaner = GenericCleaner()

        self.normalizer = normalizer if normalizer is not None else BarDataNormalizer()
        self.store = store if store is not None else DuckDBMarketStore(data_source=data_source)
        bind_data_source = getattr(self.store, "bind_data_source", None)
        if callable(bind_data_source):
            bind_data_source(data_source)
        self.raw_store = raw_store if raw_store is not None else RawDataStorage()

    def sync_daily_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        use_raw_cache: bool = True,
        force_refresh: bool = False,
    ) -> pl.DataFrame:
        """执行两层 ETL 流程同步指定股票的日 K 线行情。

        Args:
            symbol: 股票或标的代码。
            start_date: 开始日期。
            end_date: 结束日期。
            use_raw_cache: 是否使用本地 RAW 时间分区缓存（默认 True）。
            force_refresh: 是否强制向 API 拉取最新数据并刷新 RAW 缓存（默认 False）。

        Returns:
            pl.DataFrame: 最终经过完整两层 ETL 处理并落盘的数据帧。
        """
        logger.info(f"开始 2-Tier ETL 管道同步 [{symbol}] (范围: {start_date} ~ {end_date})...")

        raw_df: pl.DataFrame | None = None
        dataset = dataset_for_endpoint(self.endpoint, symbol=symbol)
        instrument = None if symbol == self.endpoint else instrument_for_symbol(symbol, self.data_source)
        key = DatasetKey(
            provider=self.data_source,
            dataset=dataset,
            endpoint=self.endpoint,
            start_date=start_date,
            end_date=end_date,
            instrument=instrument,
        )

        # 1. 检查 RAW 离线缓存
        if use_raw_cache and not force_refresh:
            raw_df = self.raw_store.load_dataset(key)
            if raw_df is not None and not raw_df.is_empty():
                logger.info(f"命中 RAW 离线时间分区缓存 [{symbol}]，跳过网络请求")

        # 2. 未命中或强制刷新时从 Fetcher 拉取
        if raw_df is None:
            raw_df = self.fetcher.fetch_daily_bars_df(
                symbol, start_date, end_date, endpoint=self.endpoint
            )
            if raw_df.is_empty():
                logger.warning(f"数据源未返回数据 [{symbol}]")
                return raw_df
            # 保存到 RAW 离线归档层
            self.raw_store.save_dataset(key, raw_df)

        # 3. 清洗 (Clean)
        cleaned_df = self.cleaner.clean(raw_df)

        # 4. 标准化 (Normalize)
        normalized_df = self.normalizer.normalize(cleaned_df)

        # 注入数据血统元数据 (Data Lineage)
        if not normalized_df.is_empty():
            if instrument:
                market_expr = pl.lit(instrument.market)
                exchange_expr = pl.lit(instrument.exchange)
                currency_expr = pl.lit(instrument.currency)
            else:
                # 动态从 ts_code/symbol 列推断市场、交易所和币种 (用于全市场同步时的单行推断)
                col_ref = pl.col("ts_code") if "ts_code" in normalized_df.columns else pl.col("symbol")
                market_expr, exchange_expr, currency_expr = infer_market_exchange_currency(col_ref)

            normalized_df = normalized_df.with_columns(
                [
                    pl.lit(self.data_source).alias("data_source"),
                    pl.lit(datetime.now()).alias("updated_at"),
                    market_expr.alias("market"),
                    exchange_expr.alias("exchange"),
                    currency_expr.alias("currency"),
                    pl.lit("raw").alias("adjustment"),
                    pl.lit("v1").alias("schema_version"),
                ]
            )

        # 5. 精炼落盘 (Load to Curated Store)
        if dataset in {"daily_bar", "stock_daily_bar", "index_daily_bar"}:
            DAILY_BAR_CONTRACT.validate(normalized_df)
        self.store.save_dataset(key, normalized_df)

        logger.info(
            f"2-Tier ETL 管道同步成功完成 [{symbol}] -> 精炼落盘 {len(normalized_df)} 条记录"
        )
        return normalized_df
