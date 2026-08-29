from datetime import date

import polars as pl
import pytest

from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.pool import MacroRiskV3Strategy


def _panel() -> pl.DataFrame:
    """前 24 天横盘 100，最后一天跌破至 80 且过热 > 65。"""
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": [100.0] * 24 + [80.0],
            "panic_index": [20.0] * 25,
            "overheat_index": [40.0] * 24 + [70.0],
        }
    )


def _price_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "symbol": ["000300.SH"] * 25,
            "close": [100.0] * 24 + [80.0],
        }
    )


def _runner() -> MacroRiskRunner:
    return MacroRiskRunner(
        MacroRiskV3Strategy(),
        symbols=("000300.SH",),
        initial_weights={"000300.SH": 1.0},
        strategy_name="macro_risk_v3",
    )


def test_run_collects_break_signal() -> None:
    report = _runner().run(_panel())
    assert len(report.signals) == 1
    signal = report.signals[0]
    assert signal.symbol == "000300.SH"
    assert signal.target_weight == 0.0
    assert signal.direction.name == "CLOSE"


def test_backtest_nav_clears_on_break() -> None:
    nav = _runner().backtest(_panel(), _price_panel())
    assert len(nav) == 25
    values = nav["nav"].to_list()
    # 前 24 天横盘收益 0，最后一天满仓承受 -20%
    assert values[23] == pytest.approx(1.0)
    assert values[24] == pytest.approx(0.8)


def test_backtest_empty_price_panel_is_cash_flat() -> None:
    nav = _runner().backtest(_panel(), pl.DataFrame())
    assert len(nav) == 25
    assert all(v == pytest.approx(1.0) for v in nav["nav"].to_list())


def test_backtest_with_commission_and_slippage() -> None:
    # 当发生从 1.0 -> 0.0 清仓换手时，扣除换手摩擦 (1.0 * (0.001 + 0.001) = 0.002)
    runner = MacroRiskRunner(
        MacroRiskV3Strategy(),
        symbols=("000300.SH",),
        initial_weights={"000300.SH": 1.0},
        strategy_name="macro_risk_v3",
        commission_rate=0.001,
        slippage_rate=0.001,
    )
    nav = runner.backtest(_panel(), _price_panel())
    values = nav["nav"].to_list()
    # 24天: 1.0; 25天: 0.8 * (1 - 0.002) = 0.7984
    assert values[24] == pytest.approx(0.8 * (1.0 - 0.002))


def test_backtest_with_deadband_filtering() -> None:
    # 设置 1.5 的死区阈值（大于单次清仓 1.0 的换手），导致调仓被过滤，不扣费且持仓不变
    runner = MacroRiskRunner(
        MacroRiskV3Strategy(),
        symbols=("000300.SH",),
        initial_weights={"000300.SH": 1.0},
        strategy_name="macro_risk_v3",
        commission_rate=0.01,
        rebalance_deadband=1.5,
    )
    nav = runner.backtest(_panel(), _price_panel())
    values = nav["nav"].to_list()
    # 调仓被忽略，不扣手续费
    assert values[24] == pytest.approx(0.8)


def test_strategy_custom_thresholds_injection() -> None:
    # 注入更高的 overheat 阈值 80.0，使 70.0 的 overheat 不再触发清仓
    strat = MacroRiskV3Strategy(overheat_threshold=80.0)
    runner = MacroRiskRunner(
        strat,
        symbols=("000300.SH",),
        initial_weights={"000300.SH": 1.0},
        strategy_name="macro_risk_v3",
    )
    report = runner.run(_panel())
    assert len(report.signals) == 0


def test_backtest_signal_takes_effect_next_day() -> None:
    """T+1 语义：T 日收盘生成的信号不影响 T 日收益，自 T+1 日按新权重生效。"""
    dates = [date(2026, 6, i + 1) for i in range(26)]
    # day24 跌破至 80（此时无信号，满仓承受 -20%）；day25 横盘但 overheat 触发清仓信号；
    # day26 再跌 -10%：若信号当日生效，该跌幅将被吸收（nav 0.72）；正确 T+1 下 nav 保持 0.8。
    panel = pl.DataFrame(
        {
            "trade_date": dates,
            "close": [100.0] * 23 + [80.0, 80.0, 72.0],
            "panic_index": [20.0] * 26,
            "overheat_index": [40.0] * 23 + [40.0, 70.0, 70.0],
        }
    )
    price_panel = pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["000300.SH"] * 26,
            "close": [100.0] * 23 + [80.0, 80.0, 72.0],
        }
    )
    nav = _runner().backtest(panel, price_panel)
    values = nav["nav"].to_list()
    # day24 满仓承受 -20%；day25 信号生成但当日不生效；day26 空仓不承受 -10%
    assert values[23] == pytest.approx(0.8)
    assert values[24] == pytest.approx(0.8)
    assert values[25] == pytest.approx(0.8)


def test_backtest_nav_starts_at_one() -> None:
    """净值首日归一为 1.0（首日为建仓日，不产生收益）。"""
    panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(5)],
            "close": [100.0, 110.0, 120.0, 130.0, 140.0],
            "panic_index": [20.0] * 5,
            "overheat_index": [40.0] * 5,
        }
    )
    # 价格面板提前 1 天（模拟真实数据早于 panel 起点），首日不应计入 pre-panel 收益
    price_panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 5, 29)] + [date(2026, 6, i + 1) for i in range(5)],
            "symbol": ["000300.SH"] * 6,
            "close": [90.0, 100.0, 110.0, 120.0, 130.0, 140.0],
        }
    )
    nav = _runner().backtest(panel, price_panel)
    values = nav["nav"].to_list()
    assert values[0] == pytest.approx(1.0)
    # 次日按 100 -> 110 计收益
    assert values[1] == pytest.approx(1.1)
