"""DatasetContract 与 DatasetKey 深度单元测试。"""

from datetime import UTC, date, datetime

import polars as pl
import pytest

from stock_core.contracts import (
    STOCK_DAILY_BAR_CONTRACT,
    DatasetContract,
    DatasetKey,
    InstrumentId,
    get_contract_for_dataset,
)
from stock_core.exceptions import DataValidationError


def test_dataset_key_properties() -> None:
    inst = InstrumentId(
        symbol="600519.SH",
        market="CN",
        exchange="SSE",
        currency="CNY",
        provider="tushare",
    )
    key = DatasetKey(
        provider="tushare",
        dataset="stock_daily_bar",
        endpoint="daily",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 12),
        instrument=inst,
    )
    assert key.task_name == "daily"
    assert len(key.request_id) == 20
    assert key.market_slug == "market=CN"
    assert key.instrument_slug == "600519.SH"

    macro_key = DatasetKey(
        provider="yfinance",
        dataset="macro_indicators",
        endpoint="macro_indicators",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 14),
        instrument=InstrumentId(
            symbol="GC=F", market="US", exchange="US_EXCHANGE", currency="USD", provider="yfinance"
        ),
    )
    assert macro_key.market_slug == "market=GLOBAL"


def test_contract_missing_columns() -> None:
    contract = DatasetContract(
        name="test_dataset",
        required_columns=("symbol", "trade_date", "close"),
        primary_keys=("symbol", "trade_date"),
        units={"price": "CNY"},
    )
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 10)],
        }
    )
    with pytest.raises(DataValidationError, match="缺少必需列"):
        contract.validate(df)


def test_contract_mixed_adjustment() -> None:
    contract = DatasetContract(
        name="test_dataset",
        required_columns=("symbol", "trade_date", "adjustment"),
        primary_keys=("symbol", "trade_date"),
        units={"price": "CNY"},
    )
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 10), date(2026, 8, 10)],
            "adjustment": ["qfq", "hfq"],
        }
    )
    with pytest.raises(DataValidationError, match="存在混合复权标记"):
        contract.validate(df)


def test_contract_ohlc_physics() -> None:
    df_invalid = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 10)],
            "open": [10.0],
            "high": [8.0],  # high < open
            "low": [9.0],
            "close": [9.5],
            "volume": [1000.0],
            "amount": [10000.0],
            "data_source": ["tushare"],
            "source_endpoint": ["daily"],
            "market": ["CN"],
            "exchange": ["SZSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [datetime.now(UTC)],
        }
    )
    with pytest.raises(DataValidationError, match="存在 1 条 OHLC 物理异常"):
        STOCK_DAILY_BAR_CONTRACT.validate(df_invalid)


def test_get_contract_for_dataset() -> None:
    assert get_contract_for_dataset("stock_daily_bar") == STOCK_DAILY_BAR_CONTRACT
    assert get_contract_for_dataset("unknown_dataset") is None
