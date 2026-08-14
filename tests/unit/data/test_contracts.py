from datetime import date, datetime, timezone

import polars as pl
import pytest

from stock.core.contracts import DAILY_BAR_CONTRACT, DatasetKey, instrument_for_symbol
from stock.data.task_registry import resolve_public_task, resolve_task
from stock.exceptions import DataValidationError


def test_dataset_key_separates_symbol_and_range() -> None:
    key_a = DatasetKey("tushare", "daily_bar", "daily", date(2026, 1, 1), date(2026, 1, 5), instrument_for_symbol("AAA", "tushare"))
    key_b = DatasetKey("tushare", "daily_bar", "daily", date(2026, 1, 1), date(2026, 1, 5), instrument_for_symbol("BBB", "tushare"))
    assert key_a.request_id != key_b.request_id


def test_stock_daily_bar_is_the_public_task_and_daily_is_internal_api() -> None:
    task = resolve_task("tushare", "stock_daily_bar")

    assert task.task_name == "stock_daily_bar"
    assert task.dataset == "stock_daily_bar"
    assert task.api_name == "daily"
    assert resolve_public_task("tushare", "stock_daily_bar").api_name == "daily"


def test_public_task_rejects_upstream_api_names() -> None:
    with pytest.raises(ValueError, match="不是项目任务名"):
        resolve_public_task("lixinger", "cn/company/candlestick")


def test_public_task_rejects_disabled_backup_bar_task() -> None:
    with pytest.raises(ValueError, match="已停用"):
        resolve_public_task("tushare", "bak_daily")
    with pytest.raises(ValueError, match="已停用"):
        resolve_task("tushare", "bak_daily")


def test_public_task_rejects_unregistered_short_name() -> None:
    with pytest.raises(ValueError, match="已注册的项目任务名"):
        resolve_public_task("tushare", "cpi")


def test_daily_contract_fails_closed_for_missing_columns() -> None:
    with pytest.raises(DataValidationError, match="缺少必需列"):
        DAILY_BAR_CONTRACT.validate(pl.DataFrame({"symbol": ["AAA"]}))


def test_daily_contract_rejects_adjustment_variants_for_same_bar() -> None:
    now_utc = datetime.now(timezone.utc)
    frame = pl.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["daily", "daily"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "normal"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )

    with pytest.raises(DataValidationError):
        DAILY_BAR_CONTRACT.validate(frame)
