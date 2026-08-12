import pytest

from stock.strategy.base import BaseStrategy
from stock.strategy.context import Context, Position
from stock.strategy.signal import Signal, SignalDirection


def test_signal_valid_weight():
    s = Signal(symbol="000001.SZ", direction=SignalDirection.BUY, target_weight=0.5)
    assert s.symbol == "000001.SZ"
    assert s.direction == SignalDirection.BUY
    assert s.target_weight == 0.5
    assert s.timestamp is not None


def test_signal_invalid_weight():
    with pytest.raises(ValueError, match="target_weight"):
        Signal(symbol="000001.SZ", direction=SignalDirection.BUY, target_weight=1.5)


def test_position_market_value_and_pnl():
    pos = Position(symbol="TEST", volume=100.0, avg_cost=10.0)
    assert pos.market_value == 1000.0
    assert pos.unrealized_pnl == 0.0

    pos.last_price = 12.0
    assert pos.market_value == 1200.0
    assert pos.unrealized_pnl == 200.0


def test_context_total_value():
    ctx = Context(initial_cash=50000.0)
    assert ctx.cash == 50000.0
    assert ctx.total_value == 50000.0

    ctx.positions["TEST"] = Position(symbol="TEST", volume=1000, avg_cost=10.0, last_price=15.0)
    assert ctx.total_value == 50000.0 + 15000.0


def test_base_strategy_is_abstract():
    with pytest.raises(TypeError):
        # 无法实例化含有 @abstractmethod 的类
        BaseStrategy()


def test_base_strategy_concrete_implementation():
    class MyStrategy(BaseStrategy):
        def on_bar(self, data):
            return [Signal(symbol="TEST", direction=SignalDirection.BUY, target_weight=0.1)]

    strat = MyStrategy()
    assert strat.context.cash == 100000.0  # 默认 Context
    signals = strat.on_bar(None)
    assert len(signals) == 1
    assert signals[0].target_weight == 0.1
