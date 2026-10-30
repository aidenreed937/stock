"""宏观风控主力资金多因子提取与合成单元测试。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock_analytics.pipelines.macro_risk.data_fetchers import (
    FetchContext,
    fetch_main_flow,
)


def test_fetch_main_flow_from_capital_game() -> None:
    # Mock feature store returning capital_game_daily
    mock_fs = MagicMock()
    mock_cg = pl.DataFrame(
        {
            "trade_date": [date(2024, 2, 5), date(2024, 2, 6)],
            "main_order_net_inflow": [-2.72e10, 1.57e10],
            "broad_etf_net_inflow": [3.75e10, 2.37e10],
            "total_turnover": [9.0e11, 9.3e11],
            "main_order_flow_ratio": [-0.0302, 0.0168],
            "broad_etf_flow_ratio": [0.0416, 0.0254],
            "divergence_score": [12.5, -5.3],
        }
    )
    mock_fs.get_domain_mart.return_value = mock_cg

    ctx = FetchContext(
        cat=MagicMock(),
        cat_yf=MagicMock(),
        fs=mock_fs,
        md=pl.DataFrame(),
    )

    df = fetch_main_flow(ctx)
    assert not df.is_empty()
    assert "composite_flow" in df.columns
    assert "main_ratio" in df.columns
    assert "etf_flow_ratio" in df.columns
    assert "divergence_score" in df.columns
    assert len(df) == 2

    # Check composite flow on 2024-02-05: (-2.72e10 + 1.2 * 3.75e10) / 9.0e11 = 1.78e10 / 9.0e11 > 0
    val_20240205 = df.filter(pl.col("trade_date") == date(2024, 2, 5))["composite_flow"][0]
    assert val_20240205 > 0  # ETF inflow successfully turns net institutional flow positive!


def test_fetch_main_flow_fallback_to_market_daily() -> None:
    mock_fs = MagicMock()
    mock_fs.get_domain_mart.side_effect = Exception("Not found")

    mock_md = pl.DataFrame(
        {
            "trade_date": [date(2024, 2, 5)],
            "main_net_inflow_ratio": [-0.0302],
        }
    )

    ctx = FetchContext(
        cat=MagicMock(),
        cat_yf=MagicMock(),
        fs=mock_fs,
        md=mock_md,
    )

    df = fetch_main_flow(ctx)
    assert not df.is_empty()
    assert "composite_flow" in df.columns
    assert "main_ratio" in df.columns
    assert "etf_flow_ratio" in df.columns
    assert "divergence_score" in df.columns
