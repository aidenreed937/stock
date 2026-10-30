"""scripts/build_soda_ash_continuous_spreads.py 单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "build_soda_ash_continuous_spreads.py"
)
_mod = run_path(str(_SCRIPT_PATH))
generate_soda_ash_weekly_spreads = _mod["generate_soda_ash_weekly_spreads"]


def test_generate_soda_ash_weekly_spreads_structure() -> None:
    """验证生成的连续价差包含标准字段且日期单调递增。"""
    df = generate_soda_ash_weekly_spreads()
    assert not df.is_empty()
    assert "trade_date" in df.columns
    assert "spread_margin_cny" in df.columns
    assert "margin_regime" in df.columns
    assert "product_price_cny" in df.columns
    assert len(df) > 300

    dates = df["trade_date"].to_list()
    assert dates == sorted(dates)


def test_margin_regime_valid_values() -> None:
    """验证生成的利润状态机值均在预定集合内。"""
    df = generate_soda_ash_weekly_spreads()
    valid_regimes = {"high_profit", "profitable", "near_breakeven", "deep_loss"}
    observed_regimes = set(df["margin_regime"].unique().to_list())
    assert observed_regimes.issubset(valid_regimes)
