from datetime import date

import polars as pl

from stock_strategy.pool import create_strategy
from stock_strategy.pool.industry_trend_tracking import IndustryTrendTrackingStrategy
from stock_strategy.signal import SignalDirection


def _make_dummy_cross(d: date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["801010.SI", "801030.SI", "801780.SI", "801080.SI"],
            "industry_name": ["农林牧渔", "基础化工", "银行", "电子"],
            "trend_momentum": [8.0, 6.0, -2.0, 4.0],
            "supply_demand_score": [80.0, 90.0, 40.0, 60.0],
            "crowding_score": [20.0, 95.0, 10.0, 50.0],
        }
    )


def test_strategy_factory_creates_trend_tracking() -> None:
    s = create_strategy("IndustryTrendTrackingStrategy", top_k=2)
    assert isinstance(s, IndustryTrendTrackingStrategy)
    assert s.top_k == 2
    assert s.rebalance_period == 63
    assert s.score_column == "trend_momentum"


def test_picks_top_k_by_trend_momentum() -> None:
    s = IndustryTrendTrackingStrategy(top_k=2, rebalance_period=1)
    signals = s.on_bar(_make_dummy_cross(date(2026, 8, 25)))
    # Top 2 by trend_momentum: 801010 (8), 801030 (6)
    syms = {sig.symbol for sig in signals}
    assert syms == {"801010.SI", "801030.SI"}
    assert all(sig.direction == SignalDirection.BUY for sig in signals)
    assert all(sig.target_weight == 0.5 for sig in signals)


def test_supply_demand_filter_excludes_low_quality() -> None:
    s = IndustryTrendTrackingStrategy(top_k=3, rebalance_period=1, supply_demand_min=50.0)
    signals = s.on_bar(_make_dummy_cross(date(2026, 8, 25)))
    syms = {sig.symbol for sig in signals}
    # 银行 supply_demand_score=40 < 50 被剔除；Top3 按 trend_momentum 排
    assert "801780.SI" not in syms
    assert syms == {"801010.SI", "801030.SI", "801080.SI"}


def test_crowding_filter_excludes_overheated() -> None:
    s = IndustryTrendTrackingStrategy(top_k=3, rebalance_period=1, crowding_max=85.0)
    signals = s.on_bar(_make_dummy_cross(date(2026, 8, 25)))
    syms = {sig.symbol for sig in signals}
    # 基础化工 crowding_score=95 > 85 被剔除
    assert "801030.SI" not in syms
    assert syms == {"801010.SI", "801780.SI", "801080.SI"}


def test_direction_quadrant_filter_excludes_risk_quadrant() -> None:
    """方向高位 × 非量价齐升（supply_demand 低）→ 排除候选。"""
    d = date(2026, 8, 25)
    df = pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["801010.SI", "801030.SI", "801780.SI", "801080.SI"],
            "industry_name": ["农林牧渔", "基础化工", "银行", "电子"],
            "trend_momentum": [8.0, 6.0, 4.0, 2.0],
            "direction_score": [80.0, 70.0, 30.0, 20.0],
            "supply_demand_score": [90.0, 30.0, 80.0, 20.0],
        }
    )
    s = IndustryTrendTrackingStrategy(
        top_k=3, rebalance_period=1, direction_high_threshold=66.0, direction_quality_min=50.0
    )
    signals = s.on_bar(df)
    syms = {sig.symbol for sig in signals}
    # 801030: direction 70>66 且 supply_demand 30<50 → 风险象限被排除
    assert "801030.SI" not in syms
    assert syms == {"801010.SI", "801780.SI", "801080.SI"}
