"""MacroSlowTopDivergenceStrategy 单元测试。"""

from datetime import date, timedelta

import polars as pl

from stock_strategy.pool.macro_slow_top_divergence import MacroSlowTopDivergenceStrategy


def _dates(n: int) -> list[date]:
    base = date(2022, 1, 3)
    return [base + timedelta(days=i) for i in range(n)]


def _df(
    n: int,
    *,
    copper: list[float] | None = None,
    cb: list[float] | None = None,
    panic: float = 45.0,
    overheat: float = 45.0,
    smart: float = 50.0,
) -> pl.DataFrame:
    """构造含慢速顶背离因子列的策略面板。

    用 rising 序列构造「越到尾部越高」的 dim_slow，默认 250 日足够让末段处于高分位。
    """
    copper = copper or [float(i) for i in range(n)]
    cb = cb or [float(i) for i in range(n)]
    return pl.DataFrame(
        {
            "trade_date": _dates(n),
            "close": [100.0] * n,
            "panic_index": [panic] * n,
            "overheat_index": [overheat] * n,
            "smart_money_pct": [smart] * n,
            "copper_gold_score": copper,
            "cb_price_score": cb,
        }
    )


def test_slow_gate_normal_off_matches_rebalance() -> None:
    """常态铜金/转债分位不高 → 慢速闸门 OFF，行为等于 v5_rebalance 常态（无信号）。"""
    n = 20
    df = _df(n, copper=[50.0] * n, cb=[50.0] * n)
    strategy = MacroSlowTopDivergenceStrategy(gate_threshold=80.0)
    # dim_slow=50 < 80 → OFF；常态无恐慌/过热 → 50/50 哑铃 → 缩放 35/35/30，无调仓
    assert strategy._slow_gate_active(df) is False
    assert len(strategy.on_bar(df)) == 0


def test_slow_gate_active_cuts_equity_to_gate_cap() -> None:
    """铜金/转债均处历史高分位 (mean>=80) → 慢速闸门 ON，权益封顶降至 gate_cap。"""
    n = 20
    df = _df(n, copper=[85.0] * n, cb=[90.0] * n)
    strategy = MacroSlowTopDivergenceStrategy(gate_threshold=80.0, gate_cap=0.3)
    assert strategy._slow_gate_active(df) is True
    signals = strategy.on_bar(df)
    # 闸门 ON 会把权益封顶从 0.7 压到 0.3，触发三腿调仓
    assert len(signals) == 3
    by_sym = {s.symbol: s for s in signals}
    assert abs(by_sym["511010.SH"].target_weight - 0.7) < 1e-6  # 固收补足 70%


def test_slow_gate_off_below_threshold() -> None:
    """dim_slow 回落到 off 阈值以下 → 闸门解除。"""
    n = 20
    df = _df(n, copper=[40.0] * n, cb=[50.0] * n)  # mean=45 < 60 → OFF
    strategy = MacroSlowTopDivergenceStrategy(gate_threshold=80.0, gate_off_threshold=60.0)
    assert strategy._slow_gate_active(df) is False


def test_slow_gate_missing_factor_cols_is_off() -> None:
    """缺少 copper/cb 因子列时 fail-closed 为不激活，不抛异常。"""
    n = 20
    df = pl.DataFrame(
        {
            "trade_date": _dates(n),
            "close": [100.0] * n,
            "panic_index": [45.0] * n,
            "overheat_index": [45.0] * n,
            "smart_money_pct": [50.0] * n,
        }
    )
    strategy = MacroSlowTopDivergenceStrategy(gate_threshold=80.0)
    assert strategy._slow_gate_active(df) is False
    assert len(strategy.on_bar(df)) == 0
