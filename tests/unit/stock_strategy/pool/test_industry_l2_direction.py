from datetime import date

import polars as pl

from stock_strategy.pool import create_strategy
from stock_strategy.pool.industry_l2_direction import IndustryL2DirectionStrategy
from stock_strategy.signal import SignalDirection


def _make_dummy_cross(d: date) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [d] * 6,
            "industry_code": ["270100", "730200", "710100", "630500", "630700", "280500"],
            "industry_name": ["半导体", "通信设备", "计算机设备", "光伏设备", "电池", "乘用车"],
            "return_60d": [12.0, 9.0, 6.0, 3.0, 0.0, -3.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0, 95.0, 30.0, 20.0],
            "revenue_growth_ttm": [0.15, 0.18, 0.05, -0.10, 0.27, 0.03],
            "profit_growth_ttm": [0.29, 0.72, 0.22, -0.20, 0.74, -0.32],
            "direction_score": [50.0, 44.0, 50.0, 2.8, 8.3, 8.3],
        }
    )


def test_strategy_factory_creates_l2_direction() -> None:
    s = create_strategy("IndustryL2DirectionStrategy", top_k=2)
    assert isinstance(s, IndustryL2DirectionStrategy)
    assert s.top_k == 2
    assert s.rebalance_period == 63
    assert s.score_column == "return_60d"
    assert s.valuation_max == 90.0


def test_picks_top_k_by_momentum_with_valuation_filter() -> None:
    """动量 Top3 + 估值防守：光伏 pe5y=95>90 被剔除。"""
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1)
    signals = s.on_bar(_make_dummy_cross(date(2026, 8, 25)))
    syms = {sig.symbol for sig in signals}
    # 动量排序：270100(12), 730200(9), 710100(6)；630500 因 pe5y=95 剔除
    assert syms == {"270100", "730200", "710100"}
    assert all(sig.direction == SignalDirection.BUY for sig in signals)
    assert all(abs(sig.target_weight - round(1.0 / 3.0, 4)) < 1e-9 for sig in signals)


def test_qlq_gate_only_keeps_double_positive() -> None:
    """量价齐升硬门：营收+净利双正才可入选。"""
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1, require_qlq=True)
    signals = s.on_bar(_make_dummy_cross(date(2026, 8, 25)))
    syms = {sig.symbol for sig in signals}
    # 双正：270100, 730200, 710100, 630700；按动量 return_60d 取 Top3（630700 动量 0 最低）
    assert syms == {"270100", "730200", "710100"}


def test_direction_gate_excludes_risk_quadrant() -> None:
    """方向防守门：方向高位 × 非量价齐升 → 剔除。"""
    d = date(2026, 8, 25)
    # 710100 计算机设备：direction 90>66 高位且 rev=-0.05/np=-0.03 双负（非量价齐升）→ 剔除
    df = pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["270100", "730200", "710100", "280500"],
            "industry_name": ["半导体", "通信设备", "计算机设备", "乘用车"],
            "return_60d": [12.0, 9.0, 6.0, 3.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0, 20.0],
            "revenue_growth_ttm": [0.15, 0.18, -0.05, -0.10],
            "profit_growth_ttm": [0.29, 0.72, -0.03, -0.05],
            "direction_score": [80.0, 44.0, 90.0, 8.3],
        }
    )
    s = IndustryL2DirectionStrategy(
        top_k=3, rebalance_period=1, direction_gate=True, direction_high_threshold=66.0
    )
    signals = s.on_bar(df)
    syms = {sig.symbol for sig in signals}
    # 710100 被剔除（高位×非量价齐升）；270100 高位但量价齐升保留；280500 低位保留
    # Top3 按动量：270100(12), 730200(9), 280500(3)
    assert syms == {"270100", "730200", "280500"}


def test_quarterly_rebalance_only_triggers_on_period() -> None:
    """默认季度调仓：首个 bar 建仓，第二个 bar 无信号。"""
    s = IndustryL2DirectionStrategy(top_k=3)
    df = _make_dummy_cross(date(2026, 8, 25))
    assert len(s.on_bar(df)) > 0  # 首 bar 建仓
    assert s.on_bar(df) == []  # 未到 rebalance_period


def test_capex_gate_excludes_capex_boom() -> None:
    """资本开支防守门：capex_growth_ttm>60 或 fix_assets_yoy>40 剔除（缺失放行）。"""
    d = date(2026, 8, 25)
    df = pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["270100", "730200", "710100", "280500"],
            "industry_name": ["半导体", "通信设备", "计算机设备", "乘用车"],
            "return_60d": [12.0, 9.0, 6.0, 3.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0, 20.0],
            "revenue_growth_ttm": [0.15, 0.18, 0.05, 0.03],
            "profit_growth_ttm": [0.29, 0.72, 0.22, -0.32],
            "capex_growth_ttm": [80.0, 20.0, None, 10.0],  # 270100 capex 洪峰 → 剔除
            "fix_assets_yoy": [50.0, 10.0, None, 5.0],
        }
    )
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1, capex_gate=True)
    signals = s.on_bar(df)
    syms = {sig.symbol for sig in signals}
    # 270100 被剔除（capex 80>60）；710100 缺失放行；Top3: 730200(9), 710100(6), 280500(3)
    assert syms == {"730200", "710100", "280500"}


def test_crowd_gate_excludes_overheated() -> None:
    """拥挤度防守门：crowding_score >= 85 剔除（缺失放行）。"""
    d = date(2026, 8, 25)
    df = pl.DataFrame(
        {
            "trade_date": [d] * 4,
            "industry_code": ["270100", "730200", "710100", "280500"],
            "industry_name": ["半导体", "通信设备", "计算机设备", "乘用车"],
            "return_60d": [12.0, 9.0, 6.0, 3.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0, 20.0],
            "revenue_growth_ttm": [0.15, 0.18, 0.05, 0.03],
            "profit_growth_ttm": [0.29, 0.72, 0.22, -0.32],
            "crowding_score": [90.0, 50.0, None, 30.0],  # 270100 拥挤 90>=85 → 剔除
        }
    )
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1, crowd_gate=True)
    signals = s.on_bar(df)
    syms = {sig.symbol for sig in signals}
    assert syms == {"730200", "710100", "280500"}


def test_panic_scale_reduces_holdings() -> None:
    """恐慌降仓：panic_index>65 时持仓降至 panic_scale 比例（保留敞口）。"""
    d = date(2026, 8, 25)
    df = pl.DataFrame(
        {
            "trade_date": [d] * 3,
            "industry_code": ["270100", "730200", "710100"],
            "industry_name": ["半导体", "通信设备", "计算机设备"],
            "return_60d": [12.0, 9.0, 6.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0],
            "panic_index": [80.0, 80.0, 80.0],  # 恐慌触发
        }
    )
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1, panic_scale=0.5, panic_thr=65.0)
    s.current_weights = {"270100": 0.3333, "730200": 0.3333, "710100": 0.3333}
    signals = s.on_bar(df)
    assert len(signals) == 3
    assert all(abs(sig.target_weight - 0.16665) < 1e-3 for sig in signals)  # 0.3333 * 0.5
    assert all(sig.direction == SignalDirection.BUY for sig in signals)


def test_panic_scale_not_triggered_when_calm() -> None:
    """恐慌未触发时正常选股，不降仓。"""
    d = date(2026, 8, 25)
    df = _make_dummy_cross(d).with_columns(pl.lit(40.0).alias("panic_index"))
    s = IndustryL2DirectionStrategy(top_k=3, rebalance_period=1, panic_scale=0.5, panic_thr=65.0)
    s.current_weights = {"270100": 0.3333}
    signals = s.on_bar(df)
    # 正常 Top3 建仓（非降仓信号）
    assert len(signals) > 0
    assert all(sig.target_weight > 0.3 for sig in signals)


def test_empty_input() -> None:
    s = IndustryL2DirectionStrategy(top_k=3)
    assert s.on_bar(pl.DataFrame()) == []
