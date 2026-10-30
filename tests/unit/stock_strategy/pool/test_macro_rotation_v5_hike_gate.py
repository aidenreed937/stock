"""MacroRotationV5HikeGateStrategy 单元测试。"""

from datetime import date, timedelta

import polars as pl

from stock_strategy.pool.macro_rotation_v5_hike_gate import (
    MacroRotationV5HikeGateStrategy,
)


def _dates(n: int) -> list[date]:
    base = date(2022, 1, 3)
    return [base + timedelta(days=i) for i in range(n)]


def _df(
    n: int,
    *,
    ffr: list[float] | float = 50.0,
    panic: float = 45.0,
    overheat: float = 45.0,
    smart: float = 50.0,
) -> pl.DataFrame:
    """构造含 ffr_chg_6m_score 因子的策略面板（score 高 = 处于加息周期中）。"""
    if isinstance(ffr, float):
        ffr = [ffr] * n
    assert len(ffr) == n
    return pl.DataFrame(
        {
            "trade_date": _dates(n),
            "close": [100.0] * n,
            "panic_index": [panic] * n,
            "overheat_index": [overheat] * n,
            "smart_money_pct": [smart] * n,
            "ffr_chg_6m_score": ffr,
        }
    )


def test_hike_gate_normal_off_matches_rebalance() -> None:
    """score 低于阈值 → 加息闸门 OFF，行为等于 v5_rebalance 常态（无信号）。"""
    n = 20
    df = _df(n, ffr=50.0)
    strategy = MacroRotationV5HikeGateStrategy(hike_gate_threshold=60.0)
    # score=50 < 60 → OFF；常态无恐慌/过热 → 50/50 哑铃 → 缩放 35/35/30，无调仓
    assert strategy._hike_gate_active(df) is False
    assert len(strategy.on_bar(df)) == 0


def test_hike_gate_active_cuts_equity_to_hike_cap() -> None:
    """score 高分位 (>=threshold) → 加息闸门 ON，权益封顶降至 hike_cap、余量转固收。"""
    n = 20
    df = _df(n, ffr=90.0)
    strategy = MacroRotationV5HikeGateStrategy(hike_gate_threshold=60.0, hike_cap=0.35)
    assert strategy._hike_gate_active(df) is True
    signals = strategy.on_bar(df)
    # 闸门 ON 把权益封顶从 0.7 压到 0.35，触发三腿调仓
    assert len(signals) == 3
    by_sym = {s.symbol: s for s in signals}
    eq_total = by_sym["510880.SH"].target_weight + by_sym["159915.SZ"].target_weight
    assert abs(eq_total - 0.35) < 1e-6  # 权益合计封顶 35%
    assert abs(by_sym["511010.SH"].target_weight - 0.65) < 1e-6  # 固收补足 65%
    assert "加息闸门ON" in by_sym["510880.SH"].reason


def test_hike_gate_releases_when_score_falls() -> None:
    """score 回落到阈值以下 → 门解除，权益封顶恢复 equity_cap（0.35 → 0.7）。"""
    n = 20
    high, low = _df(n, ffr=90.0), _df(n, ffr=50.0)
    strategy = MacroRotationV5HikeGateStrategy(hike_gate_threshold=60.0, hike_cap=0.35)
    assert len(strategy.on_bar(high)) == 3  # ON：降到 17.5/17.5/65
    signals = strategy.on_bar(low)
    assert len(signals) == 3  # OFF：恢复 35/35/30
    by_sym = {s.symbol: s for s in signals}
    assert abs(by_sym["511010.SH"].target_weight - 0.30) < 1e-6
    assert "加息闸门OFF" in by_sym["510880.SH"].reason


def test_hike_gate_threshold_boundary() -> None:
    """阈值边界：score == threshold 激活，略低于则不激活。"""
    n = 20
    strategy = MacroRotationV5HikeGateStrategy(hike_gate_threshold=60.0)
    assert strategy._hike_gate_active(_df(n, ffr=60.0)) is True
    assert strategy._hike_gate_active(_df(n, ffr=59.0)) is False


def test_hike_gate_missing_factor_col_is_off() -> None:
    """缺少 ffr_chg_6m_score 列时 fail-closed 为不激活，不抛异常。"""
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
    strategy = MacroRotationV5HikeGateStrategy(hike_gate_threshold=60.0)
    assert strategy._hike_gate_active(df) is False
    assert len(strategy.on_bar(df)) == 0
