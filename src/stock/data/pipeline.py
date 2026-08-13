"""行情数据同步与 2-Tier ETL Pipeline 编排管道。"""

from datetime import date, datetime, timezone
from typing import Any

import polars as pl

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.core.contracts import (
    DAILY_BAR_CONTRACT,
    DatasetKey,
    instrument_for_symbol,
)
from stock.data.fetcher.base import BaseDataFetcher
from stock.data.normalizer.bar_normalizer import (
    BarDataNormalizer,
    infer_market_exchange_currency,
)
from stock.data.normalizer.base import BaseDataNormalizer
from stock.data.normalizer.generic_normalizer import GenericNormalizer
from stock.data.normalizer.unit_normalizer import UnitNormalizer
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage
from stock.data.task_registry import resolve_task
from stock.exceptions import DataValidationError
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
        endpoint: str = "stock_daily_bar",
    ):
        """初始化行情 ETL 管道。

        Args:
            fetcher: 数据抓取器。
            cleaner: 数据清洗器，默认根据 endpoint 动态匹配。
            normalizer: 数据标准化器，默认 BarDataNormalizer。
            store: 精炼存储引擎，默认 DuckDBMarketStore。
            raw_store: 原始归档存储引擎，默认 RawDataStorage。
            data_source: 数据源标识名称（如 tushare, akshare）。
            endpoint: 项目任务名（如 stock_daily_bar, income）。
        """
        self.fetcher = fetcher
        self.data_source = data_source
        self.endpoint = resolve_task(data_source, endpoint).task_name

        profile = self._endpoint_quality_profile(data_source, self.endpoint)
        if cleaner is not None:
            self.cleaner = cleaner
        elif profile == "bar":
            self.cleaner = BarDataCleaner()
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

    @staticmethod
    def _endpoint_quality_profile(data_source: str, endpoint: str) -> str:
        """从数据源注册表获取质量 profile，统一决定行情与通用 ETL 路由。"""
        return resolve_task(data_source, endpoint).quality_profile

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

        # 1. 检查 RAW 离线缓存
        if use_raw_cache and not force_refresh:
            raw_df = self.raw_store.load_dataset(key)
            if raw_df is not None and not raw_df.is_empty():
                logger.info(f"命中 RAW 离线时间分区缓存 [{symbol}]，跳过网络请求")

        # 2. 未命中或强制刷新时从 Fetcher 拉取
        if raw_df is None:
            raw_df = self.fetcher.fetch_daily_bars_df(
                symbol, start_date, end_date, endpoint=task.api_name
            )
            if raw_df.is_empty():
                logger.warning(f"数据源未返回数据 [{symbol}]")
                return raw_df
            raw_df = self._clip_endpoint_date_range(raw_df, start_date, end_date)
            self._validate_endpoint_frame(raw_df, start_date, end_date)
            # 保存到 RAW 离线归档层
            self.raw_store.save_dataset(key, raw_df)

        raw_df = self._clip_endpoint_date_range(raw_df, start_date, end_date)
        self._validate_endpoint_frame(raw_df, start_date, end_date)

        # 3. 显式单位转换 (Unit Normalization)
        unit_normalizer = UnitNormalizer(self.data_source, task.api_name)
        unit_df = unit_normalizer.normalize_units(raw_df)

        # 4. 清洗 (Clean)
        cleaned_df = self.cleaner.clean(unit_df)

        # 5. 标准化 (Normalize)
        normalized_df = self.normalizer.normalize(cleaned_df)

        # 注入数据血统元数据 (Data Lineage)
        if not normalized_df.is_empty():
            if instrument:
                market_expr = pl.lit(instrument.market)
                exchange_expr = pl.lit(instrument.exchange)
                currency_expr = pl.lit(instrument.currency)
            else:
                # 动态从 ts_code/symbol 列推断市场、交易所和币种 (用于全市场同步时的单行推断)
                if "ts_code" in normalized_df.columns:
                    col_ref = pl.col("ts_code")
                    market_expr, exchange_expr, currency_expr = infer_market_exchange_currency(
                        col_ref
                    )
                elif "symbol" in normalized_df.columns:
                    col_ref = pl.col("symbol")
                    market_expr, exchange_expr, currency_expr = infer_market_exchange_currency(
                        col_ref
                    )
                else:
                    market_expr = pl.lit(
                        "CN" if self.data_source in {"tushare", "lixinger"} else "US"
                    )
                    exchange_expr = pl.lit("SOURCE")
                    currency_expr = pl.lit(
                        "CNY" if self.data_source in {"tushare", "lixinger"} else "USD"
                    )

            now_utc = datetime.now(timezone.utc)
            normalized_df = normalized_df.with_columns(
                [
                    pl.lit(self.data_source).alias("data_source"),
                    pl.lit(task.api_name).alias("source_endpoint"),
                    pl.lit(key.request_id).alias("request_id"),
                    pl.lit(now_utc).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("updated_at"),
                    market_expr.alias("market"),
                    exchange_expr.alias("exchange"),
                    currency_expr.alias("currency"),
                    pl.lit("raw").alias("adjustment"),
                    pl.lit("v2").alias("schema_version"),
                ]
            )

        # 6. 精炼落盘 (Load to Curated Store)
        if dataset in {"stock_daily_bar", "index_daily_bar"}:
            DAILY_BAR_CONTRACT.validate(normalized_df)
        self.store.save_dataset(key, normalized_df)

        logger.info(
            f"2-Tier ETL 管道同步成功完成 [{symbol}] -> 精炼落盘 {len(normalized_df)} 条记录"
        )
        return normalized_df

    def _clip_endpoint_date_range(
        self, frame: pl.DataFrame, start_date: date, end_date: date
    ) -> pl.DataFrame:
        """按接口业务日期裁剪源端超出请求范围的响应记录。"""
        date_col = next(
            (
                column
                for column in ("trade_date", "date", "end_date", "month", "quarter")
                if column in frame.columns
            ),
            None,
        )
        if not date_col or frame.is_empty():
            return frame
        values = frame.get_column(date_col).cast(pl.Utf8, strict=False)
        if date_col == "quarter":

            def quarter_value(value: str | None) -> int | None:
                if not value or "Q" not in value:
                    return None
                try:
                    year, quarter = value.split("Q", 1)
                    return int(year) * 4 + int(quarter)
                except ValueError:
                    return None

            start_value = start_date.year * 4 + ((start_date.month - 1) // 3 + 1)
            end_value = end_date.year * 4 + ((end_date.month - 1) // 3 + 1)
            keep = [
                value is not None and start_value <= value <= end_value
                for value in (quarter_value(item) for item in values.to_list())
            ]
        elif date_col == "month":
            start_value = start_date.year * 100 + start_date.month
            end_value = end_date.year * 100 + end_date.month
            keep = []
            for item in values.to_list():
                try:
                    normalized = str(item).replace("-", "")[:6]
                    keep.append(start_value <= int(normalized) <= end_value)
                except (TypeError, ValueError):
                    keep.append(False)
        else:
            start_value = int(start_date.strftime("%Y%m%d"))
            end_value = int(end_date.strftime("%Y%m%d"))
            keep = []
            for item in values.to_list():
                try:
                    normalized = str(item).replace("-", "")[:8]
                    keep.append(start_value <= int(normalized) <= end_value)
                except (TypeError, ValueError):
                    keep.append(False)
        clipped = frame.filter(pl.Series("_date_range_keep", keep))
        if len(clipped) != len(frame):
            logger.warning(
                f"接口 [{self.endpoint}] 丢弃源端请求范围外记录 {len(frame) - len(clipped)} 行 "
                f"(请求范围 {start_date} ~ {end_date}, 日期列 {date_col})"
            )
        return clipped

    def _validate_endpoint_frame(
        self, frame: pl.DataFrame, start_date: date, end_date: date
    ) -> None:
        """按源注册表契约在 RAW 落盘前 fail-closed 校验结构、主键和日期范围。"""
        meta: Any | None = None
        try:
            task = resolve_task(self.data_source, self.endpoint)
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
            column
            for column in required_columns
            if column not in frame.columns and aliases.get(column) not in frame.columns
        ]
        if required:
            raise DataValidationError(
                f"接口 [{self.data_source}/{self.endpoint}] 缺少契约字段: {required}"
            )
        keys = [
            key if key in frame.columns else aliases.get(key, key)
            for key in meta.primary_keys
            if key in frame.columns or aliases.get(key) in frame.columns
        ]
        if keys:
            if any(frame[key].null_count() for key in keys):
                raise DataValidationError(f"接口 [{self.endpoint}] 主键存在空值: {keys}")
            duplicates = len(frame) - len(frame.unique(subset=keys))
            if duplicates:
                raise DataValidationError(f"接口 [{self.endpoint}] 主键重复 {duplicates} 行")
        date_col = next((column for column in meta.date_columns if column in frame.columns), None)
        if date_col and meta.max_range_days is not None and start_date and end_date:
            if (end_date - start_date).days > meta.max_range_days:
                raise DataValidationError(
                    f"接口 [{self.endpoint}] 请求跨度超过契约上限 {meta.max_range_days} 天"
                )
