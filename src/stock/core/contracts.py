"""金融数据集身份与 Schema 契约 (Core 域纯净模型)。"""

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256

import polars as pl

from stock.exceptions import DataValidationError


@dataclass(frozen=True)
class InstrumentId:
    """跨市场标的身份。"""

    symbol: str
    market: str
    exchange: str
    currency: str
    provider: str


@dataclass(frozen=True)
class DatasetKey:
    """唯一描述一次项目任务请求，作为 RAW 缓存身份。"""

    provider: str
    dataset: str
    endpoint: str
    start_date: date
    end_date: date
    instrument: InstrumentId | None = None
    adjustment: str = "raw"
    schema_version: str = "v2"

    @property
    def task_name(self) -> str:
        """返回项目任务名；endpoint 字段保留为旧调用兼容别名。"""
        return self.endpoint

    @property
    def request_id(self) -> str:
        """返回稳定的请求指纹。"""
        payload = json.dumps(asdict(self), sort_keys=True, default=str, ensure_ascii=True)
        return sha256(payload.encode("utf-8")).hexdigest()[:20]

    @property
    def market_slug(self) -> str:
        """返回用于 Hive 目录划分的市场标识 (优先使用标的市场，否则读取接口源头注册表元数据)。"""
        if self.instrument and self.instrument.market:
            return f"market={self.instrument.market.upper()}"
        from stock.data.task_registry import get_endpoint_market

        market = get_endpoint_market(self.provider, self.endpoint)
        return f"market={market.upper()}"

    @property
    def instrument_slug(self) -> str:
        """返回可安全用于路径的标的名称。"""
        if self.instrument is None:
            return "all"
        return re.sub(r"[^A-Za-z0-9_.-]", "_", self.instrument.symbol)


@dataclass(frozen=True)
class DatasetContract:
    """数据集的结构、主键与业务语义契约。"""

    name: str
    required_columns: tuple[str, ...]
    primary_keys: tuple[str, ...]
    units: dict[str, str]

    def _validate_types_and_metadata(self, df: pl.DataFrame) -> None:
        """校验 Schema 数据类型与元数据。"""
        drift_cols = [c for c in ("raw_row_count", "clean_row_count") if c in df.columns]
        if drift_cols:
            raise DataValidationError(f"数据集 [{self.name}] 包含已废弃列: {drift_cols}")

        if "trade_date" in df.columns and df["trade_date"].dtype != pl.Date:
            t_dtype = df["trade_date"].dtype
            raise DataValidationError(
                f"数据集 [{self.name}] trade_date 须为 Date 类型，实际: {t_dtype}"
            )

        if "updated_at" in df.columns:
            dtype = df["updated_at"].dtype
            if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
                raise DataValidationError(
                    f"数据集 [{self.name}] updated_at 须为 Datetime[us, UTC] 类型，实际: {dtype}"
                )

        if "schema_version" in df.columns:
            versions = set(df.get_column("schema_version").unique().to_list())
            if "v1" in versions:
                raise DataValidationError(f"数据集 [{self.name}] 包含旧版 schema_version 'v1'")

        if "adjustment" in df.columns:
            adjustments = set(df.get_column("adjustment").drop_nulls().unique().to_list())
            if len(adjustments) > 1:
                raise DataValidationError(f"数据集 [{self.name}] 存在混合复权标记: {adjustments}")
            if "normal" in adjustments:
                raise DataValidationError(f"数据集 [{self.name}] adjustment 不得包含 'normal'")

    def _validate_ohlc_physics(self, df: pl.DataFrame) -> None:
        """校验 OHLC 物理异常与空值。"""
        if any(df[column].null_count() > 0 for column in ("open", "high", "low", "close")):
            raise DataValidationError(f"数据集 [{self.name}] OHLC 包含空值")
        physical_errors = df.filter(
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
            | (pl.col("high") < pl.col("low"))
            | (pl.col("high") < pl.col("open"))
            | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("open"))
            | (pl.col("low") > pl.col("close"))
        )
        if not physical_errors.is_empty():
            raise DataValidationError(
                f"数据集 [{self.name}] 存在 {len(physical_errors)} 条 OHLC 物理异常"
            )

    def validate(self, df: pl.DataFrame) -> None:
        """以 fail-closed 方式校验数据集。"""
        if df.is_empty():
            return

        missing = [column for column in self.required_columns if column not in df.columns]
        if missing:
            raise DataValidationError(f"数据集 [{self.name}] 缺少必需列: {missing}")

        self._validate_types_and_metadata(df)

        if any(df[column].null_count() > 0 for column in self.primary_keys):
            raise DataValidationError(f"数据集 [{self.name}] 主键包含空值")

        if self.name in {"stock_daily_bar", "index_daily_bar"}:
            self._validate_ohlc_physics(df)

        duplicate_count = len(df) - len(df.unique(subset=list(self.primary_keys)))
        if duplicate_count:
            raise DataValidationError(f"数据集 [{self.name}] 存在 {duplicate_count} 条重复主键记录")


STOCK_DAILY_BAR_CONTRACT = DatasetContract(
    name="stock_daily_bar",
    required_columns=(
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "data_source",
        "source_endpoint",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
        "updated_at",
    ),
    primary_keys=("market", "symbol", "trade_date"),
    units={"price": "quote_currency", "volume": "shares", "amount": "quote_currency"},
)

INDEX_DAILY_BAR_CONTRACT = DatasetContract(
    name="index_daily_bar",
    required_columns=(
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "data_source",
        "source_endpoint",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
        "updated_at",
    ),
    primary_keys=("market", "symbol", "trade_date"),
    units={"price": "quote_currency", "volume": "shares", "amount": "quote_currency"},
)

INDEX_VALUATION_CONTRACT = DatasetContract(
    name="index_valuation",
    required_columns=(
        "symbol",
        "target_index",
        "trade_date",
        "trailing_pe",
        "forward_pe",
        "price_to_book",
        "price_to_sales",
        "dividend_yield",
        "market_cap",
        "data_source",
        "market",
        "schema_version",
    ),
    primary_keys=("market", "symbol", "trade_date"),
    units={"pe": "ratio", "pb": "ratio", "yield": "percentage"},
)

DAILY_BAR_CONTRACT = STOCK_DAILY_BAR_CONTRACT


def instrument_for_symbol(symbol: str, provider: str) -> InstrumentId | None:  # noqa: C901, PLR0911, PLR0912
    """根据当前支持的代码约定推断跨市场标的身份。空代码表示全市场快照。"""
    if not symbol:
        return None

    symbol_upper = symbol.upper()

    # 1. 中国 A 股与中证指数 (CN) 涵盖:
    # 上交所 (.SH, .SS)、深交所 (.SZ)、北交所 (.BJ)、中证指数 (.CSI)
    if symbol_upper.endswith((".SH", ".SS")):
        return InstrumentId(symbol, "CN", "SSE", "CNY", provider)
    if symbol_upper.endswith(".SZ"):
        return InstrumentId(symbol, "CN", "SZSE", "CNY", provider)
    if symbol_upper.endswith(".BJ"):
        return InstrumentId(symbol, "CN", "BSE", "CNY", provider)
    if symbol_upper.endswith(".CSI"):
        return InstrumentId(symbol, "CN", "CSI", "CNY", provider)

    # 2. 港股 (HK)
    if symbol_upper.endswith(".HK"):
        return InstrumentId(symbol, "HK", "HKEX", "HKD", provider)

    # 3. 台股 (TW)
    if symbol_upper.endswith((".TW", ".TWO")):
        return InstrumentId(symbol, "TW", "TWSE", "TWD", provider)

    # 4. 常见其他国际市场特定后缀
    if symbol_upper.endswith(".T"):
        return InstrumentId(symbol, "JP", "TSE", "JPY", provider)
    if symbol_upper.endswith(".L"):
        return InstrumentId(symbol, "UK", "LSE", "GBP", provider)
    if symbol_upper.endswith(".PA"):
        return InstrumentId(symbol, "FR", "EURONEXT", "EUR", provider)
    if symbol_upper.endswith(".DE"):
        return InstrumentId(symbol, "DE", "XETRA", "EUR", provider)
    if symbol_upper.endswith((".TO", ".V")):
        return InstrumentId(symbol, "CA", "TSX", "CAD", provider)

    # 5. 通用泛化动态后缀处理 (针对任何未显式列出的国家/地区后缀，如 .KS 韩国、.SG 新加坡等)
    if "." in symbol_upper:
        ext = symbol_upper.rsplit(".", 1)[1]
        if ext.isalpha() and 2 <= len(ext) <= 4:
            return InstrumentId(symbol, ext, f"{ext}_EXCHANGE", "LOCAL_CURRENCY", provider)

    # 6. 全球重点指数识别
    if symbol_upper == "^N225":
        return InstrumentId(symbol, "JP", "INDEX", "JPY", provider)
    if symbol_upper == "^KS11":
        return InstrumentId(symbol, "KR", "INDEX", "KRW", provider)
    if symbol_upper == "^HSI":
        return InstrumentId(symbol, "HK", "INDEX", "HKD", provider)
    if symbol_upper == "^TWII":
        return InstrumentId(symbol, "TW", "INDEX", "TWD", provider)
    if symbol_upper == "^STI":
        return InstrumentId(symbol, "SG", "INDEX", "SGD", provider)
    if symbol_upper == "^AXJO":
        return InstrumentId(symbol, "AU", "INDEX", "AUD", provider)
    if symbol_upper.startswith("^"):
        return InstrumentId(symbol, "US", "INDEX", "USD", provider)

    # 7. 6 位数字代码或 TuShare 数据源默认 (CN)
    if symbol.isdigit() and len(symbol) == 6:
        return InstrumentId(symbol, "CN", "CN_EXCHANGE", "CNY", provider)
    if provider == "tushare":
        return InstrumentId(symbol, "CN", "CN_EXCHANGE", "CNY", provider)

    # 8. 默认无后缀及美股标的 (US)
    return InstrumentId(symbol, "US", "US_EXCHANGE", "USD", provider)
