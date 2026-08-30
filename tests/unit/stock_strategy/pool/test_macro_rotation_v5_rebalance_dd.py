"""MacroRotationV5RebalanceDDStrategy 单元测试（回撤深度确认抄底变体）。"""

from datetime import date, timedelta

import polars as pl

from stock_strategy.pool.macro_rotation_v5_rebalance_dd import MacroRotationV5RebalanceDDStrategy
from stock_strategy.signal import SignalDirection


def _df(closes: list[float], panic_last: float, overheat_last: float = 30.0) -> pl.DataFrame:
    n = len(closes)
    start = date(2026, 1, 1)
    return pl.DataFrame(
        {
            "trade_date": [start + timedelta(days=i) for i in range(n)],
            "close": closes,
            "panic_index": [50.0] * (n - 1) + [panic_last],
            "overheat_index": [30.0] * (n - 1) + [overheat_last],
            "smart_money_pct": [60.0] * n,
        }
    )


def test_rebalance_dd_downgrade_when_shallow_drawdown() -> None:
    """Panic>75 但距前120日高点回撤不足 15%（-10%）→ 冰点满仓降级为分批 14/35/51。"""
    # 130 天：前 105 天 100（高点），后 25 天阴跌至 90（回撤 -10% < 15%）
    closes = [100.0] * 105 + [95.0] * 15 + [90.0] * 10
    df = _df(closes, panic_last=80.0)

    strategy = MacroRotationV5RebalanceDDStrategy(panic_dd_full_threshold=0.15)
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    by_sym = {s.symbol: s for s in signals}
    assert abs(by_sym["510880.SH"].target_weight - 0.14) < 1e-6
    assert by_sym["510880.SH"].direction == SignalDirection.SELL
    assert abs(by_sym["511010.SH"].target_weight - 0.51) < 1e-6
    assert by_sym["511010.SH"].direction == SignalDirection.BUY
    assert "降级" in by_sym["511010.SH"].reason


def test_rebalance_dd_full_when_deep_drawdown() -> None:
    """Panic>75 且距前120日高点回撤 ≥15%（-25%）→ 正常冰点满仓 创业板70 + 固收30。"""
    # 130 天：前 100 天 100，15 天涨至 120（高点），后 15 天暴跌至 90（回撤 -25%）
    closes = [100.0] * 100 + [120.0] * 15 + [90.0] * 15
    df = _df(closes, panic_last=80.0)

    strategy = MacroRotationV5RebalanceDDStrategy(panic_dd_full_threshold=0.15)
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    by_sym = {s.symbol: s for s in signals}
    assert by_sym["510880.SH"].target_weight == 0.0
    assert by_sym["510880.SH"].direction == SignalDirection.CLOSE
    assert by_sym["159915.SZ"].target_weight == 0.7
    assert by_sym["159915.SZ"].direction == SignalDirection.BUY
    assert "全仓反击" in by_sym["159915.SZ"].reason
    assert "降级" not in by_sym["159915.SZ"].reason


def test_rebalance_dd_threshold_20_percent() -> None:
    """20% 档：回撤 -18%（≥15% 但 <20%）→ 15% 档允许满仓、20% 档降级。"""
    # 130 天：前 100 天 100，15 天涨至 110（高点），后 15 天跌至 90（回撤 -18.2%）
    closes = [100.0] * 100 + [110.0] * 15 + [90.0] * 15
    df = _df(closes, panic_last=80.0)

    # 15% 档：回撤 -18% ≥ 15% → 满仓
    s15 = MacroRotationV5RebalanceDDStrategy(panic_dd_full_threshold=0.15)
    sig15 = {s.symbol: s for s in s15.on_bar(df)}
    assert sig15["159915.SZ"].target_weight == 0.7

    # 20% 档：回撤 -18% < 20% → 降级分批
    s20 = MacroRotationV5RebalanceDDStrategy(panic_dd_full_threshold=0.20)
    sig20 = {s.symbol: s for s in s20.on_bar(df)}
    assert abs(sig20["510880.SH"].target_weight - 0.14) < 1e-6
    assert "降级" in sig20["511010.SH"].reason


def test_rebalance_dd_overheat_escape_unchanged() -> None:
    """逃顶分支不受回撤确认影响：Overheat>65 破 MA20 仍清仓。"""
    # 105 天横盘 100 后暴跌至 80（跌破均线），Overheat 最后一天 70
    closes = [100.0] * 104 + [80.0]
    df = _df(closes, panic_last=20.0, overheat_last=70.0)

    strategy = MacroRotationV5RebalanceDDStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 3
    by_sym = {s.symbol: s for s in signals}
    assert by_sym["511010.SH"].target_weight == 1.0
    assert "泡沫破裂逃顶" in by_sym["511010.SH"].reason
