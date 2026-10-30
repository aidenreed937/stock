from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock_strategy.macro.live import inspect_live_signal


def test_inspect_live_signal_invalid_strategy() -> None:
    with pytest.raises(ValueError, match="未找到策略配置"):
        inspect_live_signal(strategy_key="non_existent_strategy")


@patch("stock_strategy.macro.live.assemble_macro_panel")
@patch("stock_strategy.macro.live.load_price_panel")
def test_inspect_live_signal_with_mock_quotes(
    mock_price_panel: MagicMock,
    mock_assemble: MagicMock,
) -> None:
    # 构造 25 天历史数据
    n = 25
    panel_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(n)],
            "close": [100.0] * n,
            "panic_index": [20.0] * n,
            "overheat_index": [40.0] * n,
            "etf_flow_ratio_score": [50.0] * n,
            "divergence_score": [50.0] * n,
            "dim_valuation": [50.0] * n,
        }
    )
    mock_assemble.return_value = panel_df

    prices_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(n)] * 2,
            "symbol": ["510880.SH"] * n + ["159915.SZ"] * n,
            "close": [3.0] * n + [2.0] * n,
        }
    )
    mock_price_panel.return_value = prices_df

    res = inspect_live_signal(
        strategy_key="macro_rotation_v4_etf",
        total_capital=100_000.0,
        mock_quotes={"000985.CSI": 100.0, "510880.SH": 3.0, "159915.SZ": 2.0},
    )

    assert res.strategy_key == "macro_rotation_v4_etf"
    assert res.has_rebalance is False  # 常态平稳，未触发调仓
    assert len(res.instructions) == 2
    assert "持仓状态正常" in res.markdown_card
