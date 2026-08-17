from datetime import date

import pytest
from pydantic import ValidationError

from stock_core.models.market import DailyBar


def test_daily_bar_validation(sample_daily_bar: DailyBar) -> None:
    assert sample_daily_bar.symbol == "600000.SH"
    assert sample_daily_bar.high >= sample_daily_bar.low


def test_daily_bar_invalid_high() -> None:
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="600000.SH",
            trade_date=date(2026, 1, 5),
            open=10.0,
            high=9.0,  # 错误：最高价低于开盘价
            low=8.0,
            close=9.5,
            volume=100.0,
        )
