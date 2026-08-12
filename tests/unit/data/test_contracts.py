from datetime import date

import polars as pl
import pytest

from stock.data.contracts import DAILY_BAR_CONTRACT, DatasetKey, instrument_for_symbol
from stock.exceptions import DataValidationError


def test_dataset_key_separates_symbol_and_range() -> None:
    key_a = DatasetKey("mock", "daily_bar", "daily", date(2026, 1, 1), date(2026, 1, 5), instrument_for_symbol("AAA", "mock"))
    key_b = DatasetKey("mock", "daily_bar", "daily", date(2026, 1, 1), date(2026, 1, 5), instrument_for_symbol("BBB", "mock"))
    assert key_a.request_id != key_b.request_id


def test_daily_contract_fails_closed_for_missing_columns() -> None:
    with pytest.raises(DataValidationError, match="缺少必需列"):
        DAILY_BAR_CONTRACT.validate(pl.DataFrame({"symbol": ["AAA"]}))
