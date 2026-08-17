from datetime import date
from unittest.mock import patch

from stock_data.storage.raw_cache import _candidate_dates


def test_candidate_dates_uses_latest_authoritative_trading_date() -> None:
    with patch(
        "stock_data.update_scheduler.DataUpdateScheduler.get_latest_trading_date",
        return_value=date(2023, 1, 20),
    ):
        candidates = _candidate_dates(date(2023, 1, 23))

    assert candidates == {"20230123", "20230120"}
