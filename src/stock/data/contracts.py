"""金融数据集身份与 Schema 契约。"""

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
import re

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
    """唯一描述一次数据请求，作为 RAW 缓存身份。"""

    provider: str
    dataset: str
    endpoint: str
    start_date: date
    end_date: date
    instrument: InstrumentId | None = None
    adjustment: str = "raw"
    schema_version: str = "v1"

    @property
    def request_id(self) -> str:
        """返回稳定的请求指纹。"""
        payload = json.dumps(asdict(self), sort_keys=True, default=str, ensure_ascii=True)
        return sha256(payload.encode("utf-8")).hexdigest()[:20]

    @property
    def market_slug(self) -> str:
        """返回用于 Hive 目录划分的市场标识。"""
        if self.instrument and self.instrument.market:
            return f"market={self.instrument.market.upper()}"
        return "market=MULTI"

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

    def validate(self, df: pl.DataFrame) -> None:
        """以 fail-closed 方式校验数据集。"""
        missing = [column for column in self.required_columns if column not in df.columns]
        if missing:
            raise DataValidationError(f"数据集 [{self.name}] 缺少必需列: {missing}")
        if any(df[column].null_count() > 0 for column in self.primary_keys):
            raise DataValidationError(f"数据集 [{self.name}] 主键包含空值")
        duplicate_count = len(df) - len(df.unique(subset=list(self.primary_keys)))
        if duplicate_count:
            raise DataValidationError(
                f"数据集 [{self.name}] 存在 {duplicate_count} 条重复主键记录"
            )


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
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
    ),
    primary_keys=("market", "symbol", "trade_date", "adjustment"),
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
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
    ),
    primary_keys=("market", "symbol", "trade_date", "adjustment"),
    units={"price": "quote_currency", "volume": "shares", "amount": "quote_currency"},
)

DAILY_BAR_CONTRACT = STOCK_DAILY_BAR_CONTRACT


def dataset_for_endpoint(endpoint: str, symbol: str = "") -> str:
    """将外部接口名与标的特征映射为内部标准数据集名。

    个股 K 线归档为 stock_daily_bar，指数 K 线归档为 index_daily_bar。
    """
    if endpoint in {"daily", "daily_bar", "history", "cn/company/candlestick", "cn/index/candlestick"}:
        if endpoint == "cn/index/candlestick" or symbol.startswith("^"):
            return "index_daily_bar"
        return "stock_daily_bar"
    return endpoint.replace("/", "_")


def instrument_for_symbol(symbol: str, provider: str) -> InstrumentId | None:
    """根据当前支持的代码约定推断跨市场标的身份。空代码表示全市场快照。"""
    if not symbol:
        return None

    symbol_upper = symbol.upper()

    # 1. 中国 A 股 (CN) 涵盖: 上交所 (.SH, .SS)、深交所 (.SZ)、北交所 (.BJ)
    if symbol_upper.endswith((".SH", ".SS")):
        return InstrumentId(symbol, "CN", "SSE", "CNY", provider)
    if symbol_upper.endswith(".SZ"):
        return InstrumentId(symbol, "CN", "SZSE", "CNY", provider)
    if symbol_upper.endswith(".BJ"):
        return InstrumentId(symbol, "CN", "BSE", "CNY", provider)

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

    # 6. 全球/美股通用指数 (以 ^ 开头，如 ^GSPC 标普500, ^IXIC 纳指, ^VIX 恐慌指数)
    if symbol_upper.startswith("^"):
        return InstrumentId(symbol, "US", "INDEX", "USD", provider)

    # 7. 默认无后缀及美股标的 (US)
    return InstrumentId(symbol, "US", "US_EXCHANGE", "USD", provider)
