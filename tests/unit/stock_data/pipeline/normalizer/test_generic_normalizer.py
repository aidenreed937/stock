import polars as pl

from stock_data.pipeline.normalizer.bar_normalizer import BarDataNormalizer
from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer


def test_generic_normalizer_iso_date():
    normalizer = GenericNormalizer()
    raw_df = pl.DataFrame(
        {
            "stockCode": ["600519"],
            "date": ["2024-08-01T00:00:00+08:00"],
            "pe_ttm": [22.3],
        }
    )

    normalized = normalizer.normalize(raw_df)
    assert "symbol" in normalized.columns
    assert "trade_date" in normalized.columns
    assert normalized["symbol"][0] == "600519"
    assert str(normalized["trade_date"][0]) == "2024-08-01"


def test_generic_normalizer_maps_ts_code_and_coalesces_aliases():
    normalizer = GenericNormalizer()
    raw_df = pl.DataFrame(
        {
            "symbol": ["A", None],
            "ts_code": [None, "B"],
            "trade_date": ["2024-08-01", "2024-08-02"],
        }
    )

    normalized = normalizer.normalize(raw_df)

    assert normalized["symbol"].to_list() == ["A", "B"]
    assert "ts_code" not in normalized.columns


def test_generic_normalizer_prefers_ts_code_over_placeholder_symbol():
    normalized = GenericNormalizer().normalize(
        pl.DataFrame(
            {
                "symbol": ["ADJ_FACTOR"],
                "ts_code": ["600000.SH"],
                "trade_date": ["2024-08-01"],
            }
        )
    )

    assert normalized["symbol"].to_list() == ["600000.SH"]


def test_generic_normalizer_does_not_let_code_override_ts_code():
    normalized = GenericNormalizer().normalize(
        pl.DataFrame(
            {
                "code": ["90519"],
                "ts_code": ["600519.SH"],
                "symbol": ["600519.SH"],
                "trade_date": ["2024-08-01"],
            }
        )
    )

    assert normalized["symbol"].to_list() == ["600519.SH"]


def test_normalizers_parse_mixed_date_formats_without_dropping_rows():
    values = ["20260812", "2026-08-13", "2026/08/14", "2026-08-15T00:00:00+08:00"]
    expected = ["2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"]

    generic = GenericNormalizer().normalize(
        pl.DataFrame({"symbol": ["A"] * 4, "trade_date": values})
    )
    bars = BarDataNormalizer().normalize(
        pl.DataFrame(
            {
                "symbol": ["A"] * 4,
                "trade_date": values,
                "open": [1.0] * 4,
                "high": [1.0] * 4,
                "low": [1.0] * 4,
                "close": [1.0] * 4,
            }
        )
    )

    assert [str(value) for value in generic["trade_date"]] == expected
    assert [str(value) for value in bars["trade_date"]] == expected


def test_bar_normalizer_maps_lixinger_stock_code_to_symbol():
    normalized = BarDataNormalizer().normalize(
        pl.DataFrame(
            {
                "stockCode": ["600519"],
                "date": ["2024-08-01"],
                "open": [1800.0],
                "high": [1810.0],
                "low": [1790.0],
                "close": [1805.0],
            }
        )
    )

    assert normalized["symbol"].to_list() == ["600519"]
    assert "stockCode" not in normalized.columns
