from datetime import date

import polars as pl

from stock.data.cleaner.macro_cleaner import MacroDataCleaner
from stock.data.quality.quarantine import QuarantineStore


def test_macro_cleaner_allows_signed_values_and_quarantines_bad_ohlc(tmp_path) -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["^IRX", "CL=F", "HG=F"],
            "trade_date": [date(2026, 8, 10)] * 3,
            "open": [-0.012, -5.0, 2.7510],
            "high": [-0.010, -1.0, 2.7505],
            "low": [-0.013, -40.0, 2.7400],
            "close": [-0.011, -10.0, 2.7480],
            "volume": [0.0, 100.0, 100.0],
            "amount": [0.0, -1000.0, 100.0],
        }
    )
    quarantine = QuarantineStore(tmp_path)

    cleaned = MacroDataCleaner().clean_with_quarantine(
        frame,
        endpoint="macro_indicators",
        request_id="request-1",
        data_source="yfinance",
        quarantine=quarantine,
    )

    assert set(cleaned["symbol"].to_list()) == {"^IRX", "CL=F"}
    rejected = pl.read_parquet(tmp_path / "endpoint=macro_indicators" / "records.parquet")
    assert rejected["symbol"].to_list() == ["HG=F"]
    assert rejected["quarantine_reason"].unique().to_list() == [
        "macro_ohlc_validation_rejected"
    ]
