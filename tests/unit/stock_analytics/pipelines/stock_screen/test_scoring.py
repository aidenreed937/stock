"""个股排雷二次评分测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.scoring import (
    MIN_INDUSTRY_SIZE,
    _percentile_values,
    compute_scores,
)
from stock_analytics.pipelines.stock_screen.sources import (
    StockScreenSources,
    build_industry_map,
)


def _sources(frames: dict[str, pl.DataFrame]) -> StockScreenSources:
    return StockScreenSources(
        frames=frames,
        available={key: not value.is_empty() for key, value in frames.items()},
        data_gaps=(),
    )


def _passed() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "name": ["A", "B", "C", "D", "E"],
            "industry": [None, None, None, None, None],
        }
    )


def _industry_frames() -> dict[str, pl.DataFrame]:
    classify = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801002.SI", "801003.SI"],
            "industry_name": ["白酒Ⅱ", "电子化学品Ⅱ", "通用设备"],
            "level": ["L2", "L2", "L2"],
        }
    )
    members = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801001.SI", "801002.SI", "801002.SI", "801003.SI"],
            "con_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "in_date": [date(2010, 1, 1)] * 5,
            "out_date": [None] * 5,
        }
    )
    return {"index_classify": classify, "index_member": members}


def test_build_industry_map_filters_active_members() -> None:
    as_of = date(2026, 8, 20)
    classify = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801002.SI"],
            "industry_name": ["白酒Ⅱ", "半导体"],
            "level": ["L2", "L1"],
        }
    )
    members = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801001.SI", "801002.SI"],
            "con_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "in_date": [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 1)],
            "out_date": [None, date(2026, 1, 1), None],
        }
    )
    result = build_industry_map(
        _sources({"index_classify": classify, "index_member": members}), as_of
    )
    by_symbol = {row["symbol"]: row for row in result.to_dicts()}
    assert set(by_symbol) == {"000001.SZ"}
    assert by_symbol["000001.SZ"]["l2_name"] == "白酒Ⅱ"


def test_build_industry_map_joins_l1_independently() -> None:
    as_of = date(2026, 8, 20)
    classify = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801010.SI", "801011.SI"],
            "industry_name": ["白酒Ⅱ", "农林牧渔", "食品饮料"],
            "level": ["L2", "L2", "L1"],
        }
    )
    members = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801011.SI"],
            "con_code": ["000001.SZ", "000001.SZ"],
            "in_date": [date(2020, 1, 1), date(2020, 1, 1)],
            "out_date": [None, None],
        }
    )
    result = build_industry_map(
        _sources({"index_classify": classify, "index_member": members}), as_of
    )
    assert result.height == 1
    assert result.get_column("symbol").to_list() == ["000001.SZ"]
    assert result.get_column("l2_name").to_list() == ["白酒Ⅱ"]
    assert result.get_column("l1_name").to_list() == ["食品饮料"]


def test_percentile_uses_l2_within_industry() -> None:
    sources = _sources({**_industry_frames(), "daily_basic": _daily()})
    passed = _passed()
    scored = compute_scores(passed, sources, date(2026, 8, 20))
    scores = scored.sort("symbol").get_column("dim_value").to_list()
    assert len(scores) == 5
    assert max(scores) <= 100
    assert min(scores) >= 0


def test_percentile_falls_back_to_all_market_without_industry() -> None:
    passed = _passed()
    scored = compute_scores(passed, _sources({"daily_basic": _daily()}), date(2026, 8, 20))
    assert scored.height == 5
    assert "l2_name" in scored.columns
    assert scored.get_column("l2_name").null_count() == 5


def test_percentile_small_l2_falls_back_to_l1() -> None:
    frame = pl.DataFrame(
        {
            "symbol": [f"{i:06d}.SZ" for i in range(MIN_INDUSTRY_SIZE + 2)],
            "l2_name": [None, None] + ["tinyⅡ"] * MIN_INDUSTRY_SIZE,
            "l1_name": [None, None] + ["大行业"] * MIN_INDUSTRY_SIZE,
            "pe": list(range(MIN_INDUSTRY_SIZE + 2)),
        }
    )
    vals = _percentile_values(frame, "pe", inverse=True)
    assert max(vals) <= 100
    assert min(vals) >= 0
    tiny_group = [v for v, row in zip(vals, frame.to_dicts()) if row["l2_name"] == "tinyⅡ"]
    assert max(tiny_group) - min(tiny_group) > 0


def _daily() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
            "trade_date": [date(2026, 8, 20)] * 5,
            "pe": [10.0, 20.0, 30.0, 40.0, 50.0],
            "pb": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
