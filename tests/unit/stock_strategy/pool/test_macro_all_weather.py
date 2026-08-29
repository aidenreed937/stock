from datetime import date

import polars as pl
import pytest

from stock_strategy.pool.macro_all_weather import MacroAllWeatherStrategy


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


def test_all_weather_init():
    strat = MacroAllWeatherStrategy()
    assert strat.sym_defensive == "510880.SH"
    assert strat.sym_growth == "159915.SZ"
    assert strat.sym_core == "510300.SH"
    assert strat.sym_bond == "511010.SH"
    assert strat.sym_gold == "518880.SH"
    assert strat.initial_weights["510880.SH"] == 0.3
    assert strat.initial_weights["159915.SZ"] == 0.3
    assert strat.initial_weights["510300.SH"] == 0.2
    assert strat.initial_weights["511010.SH"] == 0.2
    assert strat.initial_weights["518880.SH"] == 0.0


def test_all_weather_insufficient_data():
    strat = MacroAllWeatherStrategy()
    df = pl.DataFrame({"trade_date": [date(2024, 1, 1)], "close": [100.0]})
    assert strat.on_bar(df) == []


def test_all_weather_phase_4_bubble_burst(base_df):
    """相态 4：狂热泡沫破裂 (Overheat > 65 & Close < MA20) -> 60% 国债 ETF + 40% 黄金 ETF。"""
    strat = MacroAllWeatherStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(80.0))  # 跌破 MA20
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(70.0))
        .otherwise(pl.col("overheat_index"))
        .alias("overheat_index"),
    )
    signals = strat.on_bar(df)
    target_weights = {sig.symbol: sig.target_weight for sig in signals}
    assert target_weights[strat.sym_defensive] == 0.0
    assert target_weights[strat.sym_growth] == 0.0
    assert target_weights[strat.sym_core] == 0.0
    assert target_weights[strat.sym_bond] == 0.6
    assert target_weights[strat.sym_gold] == 0.4


def test_all_weather_phase_1_left_support_resonance(base_df):
    """相态 1 左侧：恐慌 + 企业回购潮共振 (Panic > 65 & Repurchase >= 80 & Close < MA20) -> 权益左侧托底。"""
    strat = MacroAllWeatherStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(80.0))  # 跌破 MA20
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(68.0))
        .otherwise(pl.col("panic_index"))
        .alias("panic_index"),
        pl.lit(85.0).alias("repurchase_score"),
    )
    signals = strat.on_bar(df)
    target_weights = {sig.symbol: sig.target_weight for sig in signals}
    assert target_weights[strat.sym_core] == 0.4
    assert target_weights[strat.sym_bond] == 0.0
    assert strat.weights[strat.sym_defensive] == 0.3
    assert strat.weights[strat.sym_growth] == 0.3
    assert strat.weights[strat.sym_bond] == 0.0
    assert strat.weights[strat.sym_gold] == 0.0


def test_all_weather_phase_1_right_breakout(base_df):
    """相态 1 右侧：极度恐慌右侧突破 (Panic > 75 & Close >= MA20) -> 70% 创业板 + 30% 300 ETF。"""
    strat = MacroAllWeatherStrategy()
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
    assert target_weights[strat.sym_growth] == 0.7
    assert target_weights[strat.sym_core] == 0.3
    assert target_weights[strat.sym_defensive] == 0.0
    assert target_weights[strat.sym_bond] == 0.0


def test_all_weather_phase_3_bubble_expansion(base_df):
    """相态 3：泡沫膨胀中继 (Overheat > 65 & Close >= MA20) -> 40% 红利 + 30% 国债 + 30% 黄金。"""
    strat = MacroAllWeatherStrategy()
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
    assert target_weights[strat.sym_defensive] == 0.4
    assert target_weights[strat.sym_growth] == 0.0
    assert target_weights[strat.sym_core] == 0.0
    assert target_weights[strat.sym_bond] == 0.3
    assert target_weights[strat.sym_gold] == 0.3


def test_all_weather_phase_0_normal_preserve(base_df):
    """相态 0：常态中枢区间保持状态机持仓延续。"""
    strat = MacroAllWeatherStrategy()
    df = base_df.with_columns(
        pl.when(pl.col("trade_date") == date(2024, 1, 25))
        .then(pl.lit(100.0))
        .otherwise(pl.col("close"))
        .alias("close"),
    )
    signals = strat.on_bar(df)
    assert signals == []
    assert strat.weights[strat.sym_defensive] == 0.3
    assert strat.weights[strat.sym_growth] == 0.3
    assert strat.weights[strat.sym_core] == 0.2
    assert strat.weights[strat.sym_bond] == 0.2
    assert strat.weights[strat.sym_gold] == 0.0
