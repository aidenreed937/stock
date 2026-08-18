"""StorageCompat 单元测试。"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from stock_data.storage.compat import StorageCompat


def test_is_artifact_path() -> None:
    assert StorageCompat.is_artifact_path(Path("data.bak.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.migration.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.parquet")) is False


def test_canonical_dataset_name() -> None:
    assert StorageCompat.canonical_dataset_name("daily") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_bar") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("history") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_basic", "tushare") == "daily_basic"


def test_normalize_identity_columns() -> None:
    df = pl.DataFrame({"ts_code": ["000001.SZ"], "date": ["2026-08-10"], "close": [10.0]})
    normalized = StorageCompat.normalize_identity_columns(df)
    assert "symbol" in normalized.columns
    assert "trade_date" in normalized.columns
    assert "ts_code" not in normalized.columns
    assert "date" not in normalized.columns
    assert normalized["symbol"][0] == "000001.SZ"
    assert normalized["trade_date"][0] == "2026-08-10"


def test_normalize_datetime_columns() -> None:
    now_naive = datetime(2026, 8, 10, 12, 0, 0)
    df = pl.DataFrame({"updated_at": [now_naive]})
    normalized = StorageCompat.normalize_datetime_columns(df)
    assert normalized.schema["updated_at"] == pl.Datetime("us", "UTC")


def test_normalize_numeric_columns() -> None:
    df = pl.DataFrame({"rqyl": ["12345.6"], "rzye": ["999.0"], "text_col": ["abc"]})
    normalized = StorageCompat.normalize_numeric_columns(df)
    assert normalized.schema["rqyl"] == pl.Float64
    assert normalized.schema["rzye"] == pl.Float64
    assert normalized.schema["text_col"] == pl.String
    assert normalized["rqyl"][0] == 12345.6


def test_normalize_nested_columns_encodes_empty_struct_without_reference() -> None:
    df = pl.DataFrame({"symbol": ["600519"], "q": [{}]})

    normalized = StorageCompat.normalize_nested_columns(df)

    assert normalized.schema["q"] == pl.String
    assert normalized["q"].to_list() == ["{}"]


def test_normalize_nested_columns_casts_empty_struct_to_stable_reference() -> None:
    stable = pl.DataFrame({"q": [{"metrics": {"roe": 1.0}}]})
    empty = pl.DataFrame({"q": [{"metrics": {}}]})

    normalized = StorageCompat.normalize_nested_columns(empty, reference_frames=[stable])

    assert normalized.schema["q"] == stable.schema["q"]
    assert normalized["q"].to_list() == [{"metrics": {"roe": None}}]


def test_safe_normalize_frame() -> None:
    df = pl.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "date": ["2026-08-14"],
            "rqyl": ["500000.0"],
            "updated_at": [datetime(2026, 8, 14, 15, 0, 0, tzinfo=UTC)],
        }
    )
    safe_df = StorageCompat.safe_normalize_frame(df)
    assert "symbol" in safe_df.columns
    assert "trade_date" in safe_df.columns
    assert safe_df.schema["trade_date"] == pl.Date
    assert safe_df.schema["rqyl"] == pl.Float64
    assert safe_df.schema["updated_at"] == pl.Datetime("us", "UTC")


def test_post_process_moneyflow_hsgt_drops_legacy_symbol() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["moneyflow_hsgt"],
            "trade_date": ["2026-08-14"],
            "north_money": ["1.0"],
            "market": ["US"],
            "currency": ["USD"],
            "exchange": ["US_EXCHANGE"],
        }
    )

    normalized = StorageCompat.post_process_dataset("moneyflow_hsgt", df)

    assert "symbol" not in normalized.columns
    assert normalized.columns == ["trade_date", "north_money", "market", "currency", "exchange"]
    assert normalized["market"].to_list() == ["CN"]
    assert normalized["currency"].to_list() == ["CNY"]
    assert normalized["exchange"].to_list() == ["SOURCE"]


def test_post_process_adds_stable_identity_for_period_macro_dataset() -> None:
    normalized = StorageCompat.post_process_dataset(
        "sf_month", pl.DataFrame({"month": ["202607"], "inc_month": [1.0]})
    )

    assert normalized["symbol"].to_list() == ["sf_month"]


def test_post_process_interest_rates_drops_retired_lpr_columns() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2026-08-14"],
            "lpr_y1": [3.0],
            "lpr_y5": [3.5],
            "shibor_on": [1.0],
        }
    )

    normalized = StorageCompat.post_process_dataset("interest_rates", df)

    assert normalized.columns == ["trade_date", "shibor_on"]


def test_fred_dataset_aliases_keep_legacy_directories_readable() -> None:
    assert StorageCompat.canonical_dataset_name("FEDFUNDS", "fred") == "macro_indicators"
    assert StorageCompat.dataset_aliases("FEDFUNDS", "fred") == (
        "macro_indicators",
        "fedfunds",
    )
    assert StorageCompat.dataset_symbol_filter("FEDFUNDS", "fred") == "FEDFUNDS"
