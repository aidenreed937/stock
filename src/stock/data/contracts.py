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


DAILY_BAR_CONTRACT = DatasetContract(
    name="daily_bar",
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


def dataset_for_endpoint(endpoint: str) -> str:
    """将外部接口名映射为内部标准数据集名。"""
    if endpoint in {"daily", "history"}:
        return "daily_bar"
    raise DataValidationError(f"接口 [{endpoint}] 尚未定义可落盘的数据契约")


def instrument_for_symbol(symbol: str, provider: str) -> InstrumentId | None:
    """根据当前支持的代码约定推断标的身份。空代码表示全市场快照。"""
    if not symbol:
        return None
    if symbol.endswith(".SH"):
        return InstrumentId(symbol, "CN", "SSE", "CNY", provider)
    if symbol.endswith(".SZ"):
        return InstrumentId(symbol, "CN", "SZSE", "CNY", provider)
    return InstrumentId(symbol, "US", "NASDAQ", "USD", provider)
