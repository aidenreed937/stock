//! Black-Scholes 隐含波动率 (Implied Volatility) 快速数值求解器。

use super::bs::black_scholes_price;

/// 反解欧式期权 Black-Scholes 隐含波动率
///
/// 算法行为与 Python 版 `settlement_implied_volatility` 保持 100% 镜像一致。
/// 使用有界二分法，优先保证结果契约一致和边界行为稳定。
#[inline]
pub fn settlement_implied_volatility(
    settlement: f64,
    spot: f64,
    strike: f64,
    time_years: f64,
    rate: f64,
    is_call: bool,
) -> Option<f64> {
    if !settlement.is_finite()
        || !spot.is_finite()
        || !strike.is_finite()
        || !time_years.is_finite()
        || !rate.is_finite()
        || settlement <= 0.0
        || spot <= 0.0
        || strike <= 0.0
        || time_years <= 0.0
    {
        return None;
    }

    let discount_strike = strike * (-rate * time_years).exp();
    let lower = if is_call {
        (spot - discount_strike).max(0.0)
    } else {
        (discount_strike - spot).max(0.0)
    };
    let upper = if is_call { spot } else { discount_strike };

    if settlement <= lower || settlement >= upper {
        return None;
    }

    // 与 Python 版保持相同的有界二分流程，优先保证结果契约一致。
    let mut low = 1e-6;
    let mut high = 8.0;
    let mut low_value =
        black_scholes_price(spot, strike, time_years, rate, low, is_call) - settlement;
    let high_value =
        black_scholes_price(spot, strike, time_years, rate, high, is_call) - settlement;

    if low_value * high_value > 0.0 {
        return None;
    }

    for _ in 0..60 {
        let middle = (low + high) / 2.0;
        let value = black_scholes_price(spot, strike, time_years, rate, middle, is_call);
        if (value - settlement).abs() < 1e-8 {
            return Some(middle);
        }
        if (value - settlement) * low_value > 0.0 {
            low = middle;
            low_value = value - settlement;
        } else {
            high = middle;
        }
    }

    Some((low + high) / 2.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_iv_solver_call_and_put() {
        let spot = 3.0;
        let strike = 3.0;
        let time_years = 0.25;
        let rate = 0.02;
        let true_vol = 0.22;

        // 构造理论结算价
        let call_settle = black_scholes_price(spot, strike, time_years, rate, true_vol, true);
        let put_settle = black_scholes_price(spot, strike, time_years, rate, true_vol, false);

        // 反解
        let iv_call =
            settlement_implied_volatility(call_settle, spot, strike, time_years, rate, true)
                .unwrap();
        let iv_put =
            settlement_implied_volatility(put_settle, spot, strike, time_years, rate, false)
                .unwrap();

        assert!((iv_call - true_vol).abs() < 1e-6);
        assert!((iv_put - true_vol).abs() < 1e-6);
    }

    #[test]
    fn test_iv_boundary_conditions() {
        assert!(settlement_implied_volatility(0.0, 3.0, 3.0, 0.25, 0.02, true).is_none());
        assert!(settlement_implied_volatility(-1.0, 3.0, 3.0, 0.25, 0.02, true).is_none());
        assert!(settlement_implied_volatility(1.0, 3.0, 3.0, 0.0, 0.02, true).is_none());
        // 超过上限 (Call 价格 > Spot)
        assert!(settlement_implied_volatility(3.5, 3.0, 3.0, 0.25, 0.02, true).is_none());
    }
}
