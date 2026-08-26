"""Black-Scholes 结算价隐含波动率纯计算原语。"""

from __future__ import annotations

import math


def _normal_cdf(value: float) -> float:
    """计算标准正态分布累积分布函数。"""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_scholes_price(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    volatility: float,
    call_put: str,
) -> float:
    """计算欧式 Black-Scholes 期权价格。"""
    if time_years <= 0.0:
        intrinsic = max(spot - strike, 0.0) if call_put == "C" else max(strike - spot, 0.0)
        return intrinsic
    root_time = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * time_years) / (
        volatility * root_time
    )
    d2 = d1 - volatility * root_time
    discount = math.exp(-rate * time_years)
    if call_put == "C":
        return spot * _normal_cdf(d1) - strike * discount * _normal_cdf(d2)
    return strike * discount * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def settlement_implied_volatility(
    settlement: float,
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    call_put: str,
) -> float | None:
    """反解欧式 Black-Scholes 波动率；输入价格必须为结算价。"""
    if (
        settlement <= 0.0
        or spot <= 0.0
        or strike <= 0.0
        or time_years <= 0.0
        or call_put not in {"C", "P"}
        or not all(math.isfinite(value) for value in (settlement, spot, strike, time_years, rate))
    ):
        return None
    discount_strike = strike * math.exp(-rate * time_years)
    lower = (
        max(spot - discount_strike, 0.0) if call_put == "C" else max(discount_strike - spot, 0.0)
    )
    upper = spot if call_put == "C" else discount_strike
    if settlement <= lower or settlement >= upper:
        return None

    low, high = 1e-6, 8.0
    low_value = black_scholes_price(spot, strike, time_years, rate, low, call_put) - settlement
    high_value = black_scholes_price(spot, strike, time_years, rate, high, call_put) - settlement
    if low_value * high_value > 0.0:
        return None
    for _ in range(60):
        middle = (low + high) / 2.0
        value = black_scholes_price(spot, strike, time_years, rate, middle, call_put)
        if abs(value - settlement) < 1e-8:
            return middle
        if (value - settlement) * low_value > 0.0:
            low = middle
            low_value = value - settlement
        else:
            high = middle
    return (low + high) / 2.0


__all__ = ["black_scholes_price", "settlement_implied_volatility"]
