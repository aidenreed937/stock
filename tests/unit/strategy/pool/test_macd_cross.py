import polars as pl

from stock.strategy.pool.macd_cross import MACDCrossStrategy
from stock.strategy.signal import SignalDirection


def test_macd_golden_cross():
    # 创建一个模拟的接近金叉的数据集
    # 构造足够长的数据，让 EMA 可以平稳计算 (至少 35 条)
    # 我们故意在最后两天制造一次金叉:
    # 倒数第二天 MACD < 0, 最后一天 MACD > 0

    # 构造足够长的数据让 EMA 平稳 (至少 35 条)
    # 前面保持平稳，倒数第二天微跌，最后一天大涨，形成金叉
    prices = [10.0] * 35 + [8.0, 15.0]

    df = pl.DataFrame({"symbol": ["TEST"] * len(prices), "close": prices})

    strategy = MACDCrossStrategy(target_weight=0.3)
    signals = strategy.on_bar(df)

    assert len(signals) == 1
    assert signals[0].symbol == "TEST"
    assert signals[0].direction == SignalDirection.BUY
    assert signals[0].target_weight == 0.3
    assert signals[0].reason == "MACD_GOLDEN_CROSS"


def test_macd_dead_cross():
    # 模拟死叉
    prices = [10.0] * 35 + [12.0, 5.0]

    df = pl.DataFrame({"symbol": ["TEST"] * len(prices), "close": prices})

    strategy = MACDCrossStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 1
    assert signals[0].direction == SignalDirection.SELL
    assert signals[0].target_weight == 0.0
    assert signals[0].reason == "MACD_DEAD_CROSS"


def test_not_enough_data():
    df = pl.DataFrame({"symbol": ["TEST"] * 10, "close": [10.0] * 10})
    strategy = MACDCrossStrategy()
    assert len(strategy.on_bar(df)) == 0
