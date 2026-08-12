import polars as pl
from stock.data.normalizer.generic_normalizer import GenericNormalizer


def test_generic_normalizer_iso_date():
    normalizer = GenericNormalizer()
    raw_df = pl.DataFrame({
        "stockCode": ["600519"],
        "date": ["2024-08-01T00:00:00+08:00"],
        "pe_ttm": [22.3],
    })

    normalized = normalizer.normalize(raw_df)
    assert "symbol" in normalized.columns
    assert "trade_date" in normalized.columns
    assert normalized["symbol"][0] == "600519"
    assert str(normalized["trade_date"][0]) == "2024-08-01"
