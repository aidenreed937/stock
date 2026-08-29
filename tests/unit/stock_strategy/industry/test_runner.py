from datetime import date

import polars as pl

from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool.industry_momentum import IndustryMomentumRotationStrategy


def test_runner_backtests_nav() -> None:
    strat = IndustryMomentumRotationStrategy(top_k=2, rebalance_period=1)
    runner = IndustryStrategyRunner(
        strat,
        commission_rate=0.0001,
        slippage_rate=0.0005,
        rebalance_deadband=0.01,
    )

    days = [date(2026, 8, 20 + i) for i in range(5)]
    panel_rows = []
    price_rows = []

    for d in days:
        panel_rows.extend(
            [
                {
                    "trade_date": d,
                    "industry_code": "801010.SI",
                    "industry_name": "农业",
                    "ind_momentum": 90.0,
                },
                {
                    "trade_date": d,
                    "industry_code": "801030.SI",
                    "industry_name": "化工",
                    "ind_momentum": 80.0,
                },
                {
                    "trade_date": d,
                    "industry_code": "801040.SI",
                    "industry_name": "钢铁",
                    "ind_momentum": 40.0,
                },
            ]
        )
        price_rows.extend(
            [
                {
                    "trade_date": d,
                    "symbol": "801010.SI",
                    "close": 100.0 * (1.0 + 0.01 * (d.day - 20)),
                },
                {
                    "trade_date": d,
                    "symbol": "801030.SI",
                    "close": 50.0 * (1.0 + 0.02 * (d.day - 20)),
                },
                {"trade_date": d, "symbol": "801040.SI", "close": 20.0},
            ]
        )

    panel = pl.DataFrame(panel_rows)
    price_panel = pl.DataFrame(price_rows)

    nav_df = runner.backtest(panel, price_panel)
    assert len(nav_df) == 5
    assert "trade_date" in nav_df.columns
    assert "nav" in nav_df.columns
    assert 0.99 <= nav_df["nav"][0] <= 1.0
    assert nav_df["nav"][-1] > 1.0
