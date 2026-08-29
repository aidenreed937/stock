from datetime import date

import polars as pl
import pytest

from stock_strategy.pool.macro_meta_router import MacroMetaRouterStrategy
from stock_strategy.signal import SignalDirection


@pytest.fixture
def base_df():
    """构造包含 25 个交易日的基础 DataFrame。"""
    dates = [date(2024, 1, i) for i in range(1, 26)]
    closes = [100.0] * 24 + [100.0]
    panics = [30.0] * 25
    overheats = [30.0] * 25
    return pl.DataFrame(
        {
            "trade_date": dates,
            "close": closes,
            "panic_index": panics,
            "overheat_index": overheats,
        }
    )


def test_meta_router_init():
    strat = MacroMetaRouterStrategy()
    assert strat.sym_defensive == "000922.CSI"
    assert strat.sym_growth == "399006.SZ"
    assert strat.sym_core == "000300.SH"
    assert strat.initial_weights["000922.CSI"] == 0.4
    assert strat.initial_weights["399006.SZ"] == 0.4
    assert strat.initial_weights["000300.SH"] == 0.2


def test_meta_router_insufficient_data():
    strat = MacroMetaRouterStrategy()
    df = pl.DataFrame({"trade_date": [date(2024, 1, 1)], "close": [100.0]})
    assert strat.on_bar(df) == []


def test_meta_router_phase_4_bubble_burst(base_df):
    """相态 4：狂热泡沫破裂 (Overheat > 65 & Close < MA20) -> 全额清仓。"""
    strat = MacroMetaRouterStrategy()
    # 构造最后一日跌破均线且 Overheat = 70
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(80.0))  # MA20 约 99，当前 80 -> 跌破均线
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(70.0))
        .otherwise(pl.col("overheat_index"))
        .alias("overheat_index"),
    )
    signals = strat.on_bar(df)
    assert len(signals) == 3
    for sig in signals:
        assert sig.direction == SignalDirection.CLOSE
        assert sig.target_weight == 0.0
        assert "相态4" in sig.reason


def test_meta_router_phase_1_left_support(base_df):
    """相态 1 左侧：极度恐慌/国家队托底 (Panic > 65 & ETF >= 90 & Close < MA20) -> 50% 300 + 30% 红利 + 20% 创业板。"""
    strat = MacroMetaRouterStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(80.0))  # 跌破 MA20
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(68.0))
        .otherwise(pl.col("panic_index"))
        .alias("panic_index"),
        pl.lit(95.0).alias("etf_flow_ratio_score"),
    )
    signals = strat.on_bar(df)
    target_weights = {sig.symbol: sig.target_weight for sig in signals}
    assert target_weights[strat.sym_core] == 0.5
    assert target_weights[strat.sym_defensive] == 0.3
    assert target_weights[strat.sym_growth] == 0.2


def test_meta_router_phase_1_right_breakout(base_df):
    """相态 1 右侧：极度恐慌右侧突破 (Panic > 75 & Close >= MA20) -> 100% 创业板。"""
    strat = MacroMetaRouterStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(120.0))  # 站稳 MA20
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(80.0))
        .otherwise(pl.col("panic_index"))
        .alias("panic_index"),
    )
    signals = strat.on_bar(df)
    target_weights = {sig.symbol: sig.target_weight for sig in signals}
    assert target_weights[strat.sym_growth] == 1.0
    assert target_weights[strat.sym_defensive] == 0.0
    assert target_weights[strat.sym_core] == 0.0


def test_meta_router_phase_3_bubble_expansion(base_df):
    """相态 3：泡沫膨胀中继 (Overheat > 65 & Close >= MA20) -> 50% 红利防御。"""
    strat = MacroMetaRouterStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(120.0))  # 均线完好
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(70.0))
        .otherwise(pl.col("overheat_index"))
        .alias("overheat_index"),
    )
    signals = strat.on_bar(df)
    target_weights = {sig.symbol: sig.target_weight for sig in signals}
    assert target_weights[strat.sym_defensive] == 0.5
    assert target_weights[strat.sym_growth] == 0.0
    assert target_weights[strat.sym_core] == 0.0


def test_meta_router_phase_2_valuation_bottom(base_df):
    """相态 2：估值大底 (dim_valuation <= 15) -> 40% 红利 + 30% 300 + 30% 创业板。"""
    strat = MacroMetaRouterStrategy()
    df = base_df.with_columns(
        pl.lit(10.0).alias("dim_valuation"),
    )
    strat.on_bar(df)
    assert strat.weights[strat.sym_defensive] == 0.4
    assert strat.weights[strat.sym_core] == 0.3
    assert strat.weights[strat.sym_growth] == 0.3


def test_meta_router_phase_0_normal_preserve(base_df):
    """相态 0：常态中枢区间保持状态机持仓延续。"""
    strat = MacroMetaRouterStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(100.0))
        .otherwise(pl.col("close"))
        .alias("close"),
    )
    signals = strat.on_bar(df)
    # 常态下持仓不变，不产生多余换手信号
    assert signals == []
    assert strat.weights[strat.sym_defensive] == 0.4
    assert strat.weights[strat.sym_growth] == 0.4
    assert strat.weights[strat.sym_core] == 0.2
