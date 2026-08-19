"""期权结算价波动率代理 Mart 测试。"""

from datetime import date

import polars as pl
import pytest

from stock_analytics.marts.option_volatility import (
    _black_scholes_price,
    build_settlement_iv_proxy_mart,
    settlement_implied_volatility,
)


def test_settlement_implied_volatility_recovers_black_scholes_input() -> None:
    spot = 100.0
    strike = 100.0
    time_years = 30.0 / 365.0
    rate = 0.02
    expected = 0.25
    settlement = _black_scholes_price(spot, strike, time_years, rate, expected, "C")

    result = settlement_implied_volatility(settlement, spot, strike, time_years, rate, "C")

    assert result == pytest.approx(expected, abs=1e-6)


def test_settlement_implied_volatility_rejects_invalid_price() -> None:
    assert settlement_implied_volatility(0.0, 100.0, 100.0, 0.1, 0.0, "C") is None
    assert settlement_implied_volatility(100.0, 100.0, 100.0, 0.1, 0.0, "C") is None


def test_build_settlement_iv_proxy_mart_aggregates_call_and_put() -> None:
    trade_date = date(2026, 8, 1)
    maturity = date(2026, 9, 1)
    spot = 100.0
    strike = 100.0
    rate = 0.02
    volatility = 0.2
    time_years = (maturity - trade_date).days / 365.0
    call_settle = _black_scholes_price(spot, strike, time_years, rate, volatility, "C")
    put_settle = _black_scholes_price(spot, strike, time_years, rate, volatility, "P")

    result = build_settlement_iv_proxy_mart(
        pl.DataFrame(
            {
                "symbol": ["C1", "P1"],
                "trade_date": [trade_date, trade_date],
                "settle": [call_settle, put_settle],
            }
        ),
        pl.DataFrame(
            {
                "symbol": ["C1", "P1"],
                "call_put": ["C", "P"],
                "exercise_price": [strike, strike],
                "maturity_date": [maturity, maturity],
                "opt_code": ["OP000300.SH", "OP000300.SH"],
            }
        ),
        pl.DataFrame(
            {
                "symbol": ["000300.SH"],
                "trade_date": [trade_date],
                "close": [spot],
            }
        ),
        risk_free_rates=pl.DataFrame({"trade_date": [trade_date], "risk_free_rate": [rate]}),
        underlying_symbols=("000300.SH",),
    )

    row = result.row(0, named=True)
    assert row["underlying_symbol"] == "000300.SH"
    assert row["settlement_iv_proxy_valid_count"] == 2
    assert row["settlement_iv_proxy_call_count"] == 1
    assert row["settlement_iv_proxy_put_count"] == 1
    assert row["settlement_iv_proxy_median"] == pytest.approx(volatility, abs=1e-6)
    assert row["settlement_iv_proxy_put_call_skew"] == pytest.approx(0.0, abs=1e-6)


def test_build_settlement_iv_proxy_mart_empty_has_stable_schema() -> None:
    result = build_settlement_iv_proxy_mart(pl.DataFrame(), pl.DataFrame(), pl.DataFrame())

    assert result.is_empty()
    assert "settlement_iv_proxy_median" in result.columns
