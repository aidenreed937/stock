"""个股排雷通过申万黄金层构建行业映射测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.industry_map import build_industry_map
from stock_analytics.pipelines.stock_screen.sources import StockScreenSources


def test_golden_industry_map_qualifies_tushare_symbols() -> None:
    sources = StockScreenSources(
        frames={
            "stock_basic": pl.DataFrame({"symbol": ["000001.SZ"]}),
            "sw_2021_industry_member_golden": pl.DataFrame(
                {
                    "symbol": ["000001", "000001"],
                    "industry_code": ["110000", "110100"],
                    "industry_name": ["一级", "二级"],
                    "level": ["L1", "L2"],
                    "valid_from": [None, None],
                    "valid_to": [None, None],
                    "src": ["TUSHARE", "TUSHARE"],
                    "is_canonical": [True, True],
                }
            ),
        },
        available={},
        data_gaps=(),
    )

    result = build_industry_map(sources, date(2026, 9, 4))

    assert result.to_dicts() == [{"symbol": "000001.SZ", "l2_name": "二级", "l1_name": "一级"}]
