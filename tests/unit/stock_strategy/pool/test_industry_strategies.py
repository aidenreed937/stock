from datetime import date

import polars as pl

from stock_strategy.pool import create_strategy
from stock_strategy.pool.industry_meta_router import IndustryMetaRouterStrategy
from stock_strategy.pool.industry_momentum import IndustryMomentumRotationStrategy
from stock_strategy.pool.industry_reversal import IndustryCrowdingReversalStrategy
from stock_strategy.pool.industry_scissors import IndustrySupplyDemandScissorsStrategy
from stock_strategy.signal import SignalDirection


def _make_dummy_cross(d: date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["801010.SI", "801030.SI", "801780.SI", "801080.SI"],
            "industry_name": ["农林牧渔", "基础化工", "银行", "电子"],
            "close": [10.0, 20.0, 30.0, 40.0],
            "ind_momentum": [90.0, 80.0, 30.0, 70.0],
            "ind_scissors": [85.0, 70.0, 20.0, 95.0],
            "ind_crowding": [20.0, 90.0, 10.0, 60.0],
            "ind_valuation": [50.0, 40.0, 90.0, 30.0],
            "ind_smart_flow": [80.0, 60.0, 40.0, 85.0],
            "composite_industry_score": [80.0, 70.0, 40.0, 75.0],
            "panic_index": [50.0, 50.0, 50.0, 50.0],
            "overheat_index": [50.0, 50.0, 50.0, 50.0],
            "benchmark_close": [100.0, 100.0, 100.0, 100.0],
            "benchmark_ma20": [95.0, 95.0, 95.0, 95.0],
        }
    )


def test_strategy_factory_creates_industry_strategies() -> None:
    s1 = create_strategy("IndustryMomentumRotationStrategy", top_k=2)
    assert isinstance(s1, IndustryMomentumRotationStrategy)
    assert s1.top_k == 2

    s2 = create_strategy("IndustryCrowdingReversalStrategy", crowding_max=80.0)
    assert isinstance(s2, IndustryCrowdingReversalStrategy)

    s3 = create_strategy("IndustrySupplyDemandScissorsStrategy")
    assert isinstance(s3, IndustrySupplyDemandScissorsStrategy)

    s4 = create_strategy("IndustryMetaRouterStrategy")
    assert isinstance(s4, IndustryMetaRouterStrategy)


def test_momentum_rotation_picks_top_k() -> None:
    s = IndustryMomentumRotationStrategy(top_k=2, rebalance_period=1)
    df = _make_dummy_cross(date(2026, 8, 25))
    signals = s.on_bar(df)
    assert len(signals) == 2
    # Top 2 by ind_momentum: 801010.SI (90) and 801030.SI (80)
    syms = {sig.symbol for sig in signals}
    assert syms == {"801010.SI", "801030.SI"}
    assert all(sig.direction == SignalDirection.BUY for sig in signals)
    assert all(sig.target_weight == 0.5 for sig in signals)


def test_crowding_reversal_excludes_crowded() -> None:
    s = IndustryCrowdingReversalStrategy(
        top_k=2, rebalance_period=1, crowding_max=85.0, valuation_min=40.0
    )
    df = _make_dummy_cross(date(2026, 8, 25))
    signals = s.on_bar(df)
    assert len(signals) == 2
    # 801030.SI is crowded (90.0 > 85.0) -> excluded
    # Uncrowded with val >= 40: 801010.SI (val=50, mom=90), 801780.SI (val=90, mom=30)
    syms = {sig.symbol for sig in signals}
    assert "801030.SI" not in syms
    assert syms == {"801010.SI", "801780.SI"}


def test_scissors_strategy_ranks_composite_scissors() -> None:
    s = IndustrySupplyDemandScissorsStrategy(top_k=2, rebalance_period=1)
    df = _make_dummy_cross(date(2026, 8, 25))
    signals = s.on_bar(df)
    assert len(signals) == 2
    # Top 2 by 0.6*scissors + 0.4*flow:
    # 801080 (0.6*95 + 0.4*85 = 91), 801010 (0.6*85 + 0.4*80 = 83)
    syms = {sig.symbol for sig in signals}
    assert syms == {"801080.SI", "801010.SI"}


def test_meta_router_switches_on_panic() -> None:
    s = IndustryMetaRouterStrategy(
        rebalance_period=1,
        panic_threshold=70.0,
        defensive_industries=("801780.SI", "801950.SI"),
    )
    df = _make_dummy_cross(date(2026, 8, 25)).with_columns(pl.lit(75.0).alias("panic_index"))
    signals = s.on_bar(df)
    assert len(signals) == 2
    syms = {sig.symbol for sig in signals}
    assert syms == {"801780.SI", "801950.SI"}
    assert all(sig.target_weight == 0.5 for sig in signals)
