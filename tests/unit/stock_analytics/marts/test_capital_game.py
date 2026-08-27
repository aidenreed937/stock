"""全市场资金博弈与筹码结构日频 Mart 单元测试。"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.marts.capital_game import (
    STATE_ALL_RESONANCE,
    STATE_BALANCED_ROTATION,
    STATE_BOTTOM_SUPPORT,
    STATE_HIGH_DISTRIBUTION,
    STATE_ICE_PANIC,
    STATE_LEVERAGE_EUPHORIA,
    build_capital_game_frame,
)


def _make_dummy_data():
    dates = [
        date(2025, 4, 7),
        date(2025, 4, 8),
        date(2026, 1, 27),
        date(2026, 1, 28),
    ]
    turnover = pl.DataFrame(
        {
            "trade_date": dates,
            "total_turnover": [1.5e12, 1.6e12, 2.8e12, 2.9e12],
        }
    )
    etf_flow = pl.DataFrame(
        {
            "trade_date": dates,
            "total_etf_net_inflow": [4.0e10, 9.6e10, -5.0e10, -1.3e11],
            "broad_etf_net_inflow": [3.8e10, 9.4e10, -5.2e10, -1.4e11],
            "sector_etf_net_inflow": [2.0e9, 2.0e9, 2.0e9, 1.0e10],
        }
    )
    margin = pl.DataFrame(
        {
            "trade_date": dates + dates,
            "exchange_id": ["SSE"] * 4 + ["SZSE"] * 4,
            "rzmre": [5e10, 6e10, 1.4e11, 1.5e11] * 2,
            "rzche": [7e10, 8e10, 1.3e11, 1.3e11] * 2,
            "rzye": [9e11, 9e11, 1.3e12, 1.3e12] * 2,
        }
    )
    moneyflow = pl.DataFrame(
        {
            "trade_date": dates,
            "buy_elg_amount": [1e11, 8e10, 2e11, 2e11],
            "sell_elg_amount": [1.1e11, 1.0e11, 2.1e11, 2.1e11],
            "buy_lg_amount": [1e11, 8e10, 2e11, 2e11],
            "sell_lg_amount": [1.2e11, 1.2e11, 2.1e11, 2.1e11],
            "buy_sm_amount": [5e10, 8e10, 1e11, 1.2e11],
            "sell_sm_amount": [4e10, 2e10, 9e10, 1.0e11],
        }
    )
    dragon_tiger = pl.DataFrame(
        {
            "trade_date": dates,
            "inst_net_buy_amount": [1e9, 1.1e9, 8e8, 1.1e9],
            "hot_money_net_buy_amount": [5e8, 8e8, 2e8, 3e8],
        }
    )
    block_trade = pl.DataFrame(
        {
            "trade_date": dates,
            "block_trade_discount_rate_median": [-0.05, -0.04, -0.06, -0.07],
        }
    )
    cyq_perf = pl.DataFrame(
        {
            "trade_date": dates,
            "winner_rate": [12.0, 8.5, 91.0, 93.5],
            "cost_5pct": [10.0, 10.0, 20.0, 20.0],
            "cost_50pct": [12.0, 12.0, 25.0, 25.0],
            "cost_95pct": [15.0, 15.0, 32.0, 32.0],
        }
    )
    return turnover, etf_flow, margin, moneyflow, dragon_tiger, block_trade, cyq_perf


def test_capital_game_empty():
    res = build_capital_game_frame(
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
    )
    assert res.is_empty()


def test_capital_game_frame_computation():
    turnover, etf_flow, margin, moneyflow, dragon_tiger, block_trade, cyq_perf = _make_dummy_data()
    res = build_capital_game_frame(
        etf_flow=etf_flow,
        margin=margin,
        moneyflow=moneyflow,
        dragon_tiger=dragon_tiger,
        block_trade=block_trade,
        cyq_perf=cyq_perf,
        market_turnover=turnover,
    )
    assert not res.is_empty()
    assert res.height == 4
    assert "trade_date" in res.columns
    assert "etf_flow_ratio" in res.columns
    assert "margin_flow_ratio" in res.columns
    assert "main_order_flow_ratio" in res.columns
    assert "retail_order_flow_ratio" in res.columns
    assert "divergence_score" in res.columns
    assert "game_state" in res.columns

    # 验证无量纲比率
    row_apr8 = res.filter(pl.col("trade_date") == date(2025, 4, 8)).to_dicts()[0]
    assert row_apr8["etf_flow_ratio"] > 0.05  # 960亿 / 1.6万亿 > 5%
    assert row_apr8["margin_flow_ratio"] < 0  # 偿还大于买入

    # 验证分歧度取值范围在 [-100, 100]
    scores = res["divergence_score"].drop_nulls().to_list()
    assert all(-100.0 <= s <= 100.0 for s in scores)


def test_capital_game_states_rule_coverage():
    # 构造能够触发不同状态的测试数据
    turnover = pl.DataFrame(
        {
            "trade_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "total_turnover": [1e12, 1e12],
        }
    )
    # 模拟 BOTTOM_SUPPORT: 极高 ETF (百分位高), 极低两融与极低获利盘
    etf_high = pl.DataFrame(
        {
            "trade_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "total_etf_net_inflow": [1e11, 1e11],
        }
    )
    margin_low = pl.DataFrame(
        {
            "trade_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "rzmre": [1e10, 1e10],
            "rzche": [5e10, 5e10],  # 净流出
            "rzye": [1e12, 1e12],
        }
    )
    cyq_low = pl.DataFrame(
        {
            "trade_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "winner_rate": [5.0, 5.0],
        }
    )

    res = build_capital_game_frame(
        etf_flow=etf_high,
        margin=margin_low,
        moneyflow=pl.DataFrame(),
        dragon_tiger=pl.DataFrame(),
        block_trade=pl.DataFrame(),
        cyq_perf=cyq_low,
        market_turnover=turnover,
    )
    assert not res.is_empty()
    # 验证状态为有效枚举标签
    states = res["game_state"].to_list()
    valid_states = {
        STATE_BOTTOM_SUPPORT,
        STATE_HIGH_DISTRIBUTION,
        STATE_LEVERAGE_EUPHORIA,
        STATE_ICE_PANIC,
        STATE_ALL_RESONANCE,
        STATE_BALANCED_ROTATION,
    }
    assert all(s in valid_states for s in states)
