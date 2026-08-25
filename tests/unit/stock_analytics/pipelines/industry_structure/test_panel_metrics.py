"""行业估值面板异常值处理测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_metrics_batch import (
    _valuation_base_frame,
)
from stock_analytics.pipelines.industry_structure.pb_roe import _extract_pb_roe_cols


def test_valuation_base_frame_treats_nonpositive_pe_as_missing() -> None:
    raw = pl.DataFrame(
        {
            "symbol": ["330000", "340000"],
            "trade_date": [date(2026, 8, 24)] * 2,
            "pe_ttm.ew": [-36039.956838, 20.0],
            "pb.ew": [2.2, 1.8],
            "dyr.ew": [0.017, 0.02],
        }
    )

    result = _valuation_base_frame(
        raw,
        {"330000": "801110.SI", "340000": "801120.SI"},
    )

    invalid_pe = result.filter(pl.col("industry_code") == "801110.SI")["pe_ttm"][0]
    valid_pe = result.filter(pl.col("industry_code") == "801120.SI")["pe_ttm"][0]
    assert invalid_pe is None
    assert valid_pe == 20.0


def test_pb_roe_does_not_derive_roe_from_nonpositive_pe() -> None:
    raw = pl.DataFrame(
        {
            "symbol": ["330000", "340000"],
            "pb.ew": [2.2, 1.8],
            "pe_ttm.ew": [-36039.956838, 20.0],
        }
    )

    result = _extract_pb_roe_cols(raw)

    assert result["symbol"].to_list() == ["340000"]
