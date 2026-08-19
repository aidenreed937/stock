"""申万行业日行情层级归属补充测试。"""

import polars as pl

from stock_data.pipeline.normalizer.sw_daily_enricher import (
    enrich_sw_daily_frame,
    normalize_sw_daily_identity,
)


def test_normalize_sw_daily_identity_fills_legacy_null_symbol() -> None:
    frame = pl.DataFrame(
        {
            "symbol": [None],
            "ts_code": ["801010.SI"],
            "index_id": [None],
        }
    )

    normalized = normalize_sw_daily_identity(frame)

    assert normalized["symbol"].to_list() == ["801010.SI"]
    assert "ts_code" not in normalized.columns
    assert "index_id" not in normalized.columns


def test_enrich_sw_daily_frame_uses_only_sw2021_and_preserves_unmapped_rows() -> None:
    classification = pl.DataFrame(
        {
            "index_code": ["801010.SI", "801012.SI", "851923.SI", "801010.SI"],
            "level": ["L1", "L2", "L3", "L1"],
            "industry_code": ["110000", "110100", "490303", "999999"],
            "industry_name": ["农林牧渔", "种植业", "期货", "旧口径"],
            "parent_code": [None, "110000", "490300", None],
            "src": ["SW2021", "SW2021", "SW2021", "SW2014"],
        }
    )
    frame = pl.DataFrame(
        {
            "symbol": ["801010.SI", "801012.SI", "851923.SI", "801001.SI"],
            "trade_date": ["2026-08-18"] * 4,
            "close": [100.0, 101.0, 102.0, 103.0],
        }
    )

    enriched = enrich_sw_daily_frame(frame, classification)

    assert enriched["industry_level"].to_list() == ["L1", "L2", "L3", None]
    assert enriched["classification"].to_list() == ["SW2021", "SW2021", "SW2021", None]
    assert enriched["classification_status"].to_list() == [
        "mapped",
        "mapped",
        "mapped",
        "unmapped",
    ]
    assert enriched["industry_code"].to_list() == ["110000", "110100", "490303", None]


def test_enrich_sw_daily_frame_marks_missing_dictionary() -> None:
    frame = pl.DataFrame({"symbol": ["801010.SI"], "trade_date": ["2026-08-18"], "close": [100.0]})

    enriched = enrich_sw_daily_frame(frame, None)

    assert enriched["classification_status"].to_list() == ["metadata_unavailable"]
    assert enriched["industry_level"].to_list() == [None]


def test_enrich_sw_daily_frame_marks_missing_identity_as_unmapped() -> None:
    classification = pl.DataFrame(
        {
            "index_code": ["801010.SI"],
            "level": ["L1"],
            "industry_code": ["110000"],
            "src": ["SW2021"],
        }
    )
    frame = pl.DataFrame({"trade_date": ["2026-08-18"], "close": [100.0]})

    enriched = enrich_sw_daily_frame(frame, classification)

    assert enriched["classification_status"].to_list() == ["unmapped"]
    assert enriched["symbol"].to_list() == [None]
