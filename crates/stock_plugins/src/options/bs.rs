//! Black-Scholes 定价公式与标准正态分布数学工具。

use std::f64::consts::SQRT_2;

/// 高精度标准正态分布累计分布函数 (CDF)
///
/// 使用基于 erf 的精确数学实现，精度与 Python math.erf 保持完全一致。
#[inline]
pub fn normal_cdf(x: f64) -> f64 {
    0.5 * (1.0 + libm::erf(x / SQRT_2))
}

/// 高精度标准正态分布概率密度函数 (PDF)
#[inline]
pub fn normal_pdf(x: f64) -> f64 {
    const INV_SQRT_2PI: f64 = 0.398942280401432677939946059934;
    INV_SQRT_2PI * (-0.5 * x * x).exp()
}

/// Black-Scholes 欧式期权理论价格
///
/// 当 `time_years <= 0` 时直接返回内在价值。
#[inline]
pub fn black_scholes_price(
    spot: f64,
    strike: f64,
    time_years: f64,
    rate: f64,
    volatility: f64,
    is_call: bool,
) -> f64 {
    if time_years <= 0.0 {
        return if is_call {
            (spot - strike).max(0.0)
        } else {
            (strike - spot).max(0.0)
        };
    }
    if volatility <= 0.0 {
        let discount_strike = strike * (-rate * time_years).exp();
        return if is_call {
            (spot - discount_strike).max(0.0)
        } else {
            (discount_strike - spot).max(0.0)
        };
    }

    let root_time = time_years.sqrt();
    let d1 = ((spot / strike).ln() + (rate + 0.5 * volatility * volatility) * time_years)
        / (volatility * root_time);
    let d2 = d1 - volatility * root_time;
    let discount = (-rate * time_years).exp();

    if is_call {
        spot * normal_cdf(d1) - strike * discount * normal_cdf(d2)
    } else {
        strike * discount * normal_cdf(-d2) - spot * normal_cdf(-d1)
    }
}

/// Black-Scholes Vega (对波动率的偏导数)
#[inline]
pub fn black_scholes_vega(
    spot: f64,
    strike: f64,
    time_years: f64,
    rate: f64,
    volatility: f64,
) -> f64 {
    if time_years <= 0.0 || volatility <= 0.0 {
        return 0.0;
    }
    let root_time = time_years.sqrt();
    let d1 = ((spot / strike).ln() + (rate + 0.5 * volatility * volatility) * time_years)
        / (volatility * root_time);
    spot * root_time * normal_pdf(d1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normal_cdf_bounds() {
        assert!((normal_cdf(0.0) - 0.5).abs() < 1e-6);
        assert!((normal_cdf(1.96) - 0.9750021).abs() < 1e-4);
        assert!((normal_cdf(-1.96) - 0.0249979).abs() < 1e-4);
    }

    #[test]
    fn test_black_scholes_call_price() {
        let spot = 100.0;
        let strike = 100.0;
        let time_years = 1.0;
        let rate = 0.05;
        let vol = 0.2;
        let price = black_scholes_price(spot, strike, time_years, rate, vol, true);
        // 理论价约为 10.45058
        assert!((price - 10.45058).abs() < 1e-2);
    }
}
