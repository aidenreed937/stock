from datetime import date

import polars as pl

from stock_strategy.macro.walk_forward import (
    WalkForwardResult,
    WalkForwardSlice,
    render_walk_forward_markdown,
    run_walk_forward_analysis,
)


def test_walk_forward_insufficient_data() -> None:
    macro_panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1 + i) for i in range(10)],
            "close": [100.0] * 10,
            "panic_index": [50.0] * 10,
            "overheat_index": [50.0] * 10,
        }
    )
    res = run_walk_forward_analysis(
        strategy_name="test_strat",
        strategy_spec={"strategy": "macro_risk_v3"},
        macro_panel=macro_panel,
        price_panel=pl.DataFrame(),
        train_years=3,
        test_years=1,
    )
    assert res is None


def test_render_walk_forward_markdown() -> None:
    slice1 = WalkForwardSlice(
        slice_index=1,
        is_start=date(2015, 1, 1),
        is_end=date(2017, 12, 31),
        oos_start=date(2018, 1, 1),
        oos_end=date(2018, 12, 31),
        is_trading_days=750,
        oos_trading_days=250,
        is_cagr=10.0,
        is_max_dd=15.0,
        is_sharpe=0.8,
        oos_cagr=8.0,
        oos_max_dd=12.0,
        oos_sharpe=0.7,
        wfe_ratio=0.8,
    )
    res = WalkForwardResult(
        strategy_name="macro_rotation_v5",
        slices=[slice1],
        stitched_oos_nav=pl.DataFrame({"trade_date": [date(2018, 1, 1)], "nav": [1.0]}),
        full_oos_cagr=8.5,
        full_oos_max_dd=14.2,
        full_oos_sharpe=0.75,
        avg_wfe=0.82,
    )
    md = render_walk_forward_markdown([res])
    assert "Walk-Forward 滚动样本外检验" in md
    assert "macro_rotation_v5" in md
    assert "0.82" in md
    assert "极强抗过拟合" in md
