use polars::prelude::*;
use pyo3::prelude::*;
use pyo3_polars::derive::polars_expr;
#[cfg(feature = "extension-module")]
use pyo3_polars::PolarsAllocator;

#[cfg(feature = "extension-module")]
#[global_allocator]
static ALLOC: PolarsAllocator = PolarsAllocator::new();

pub mod options;

use options::iv::settlement_implied_volatility;

/// Polars 表达式插件：极速 Black-Scholes 隐含波动率 (IV) 向量化求解
///
/// 参数 (Series 切片):
/// 0: settlement (f64)
/// 1: spot (f64)
/// 2: strike (f64)
/// 3: time_years (f64)
/// 4: rate (f64)
/// 5: call_put (str, "C" / "P")
#[polars_expr(output_type=Float64)]
fn fast_bs_implied_volatility(inputs: &[Series]) -> PolarsResult<Series> {
    if inputs.len() < 6 {
        return Err(PolarsError::ComputeError(
            "fast_bs_implied_volatility requires 6 arguments: [settlement, spot, strike, time_years, rate, call_put]".into(),
        ));
    }

    let settlement = inputs[0].f64()?;
    let spot = inputs[1].f64()?;
    let strike = inputs[2].f64()?;
    let time_years = inputs[3].f64()?;
    let rate = inputs[4].f64()?;
    let call_put = inputs[5].str()?;

    let out: Float64Chunked = settlement
        .into_iter()
        .zip(spot.into_iter())
        .zip(strike.into_iter())
        .zip(time_years.into_iter())
        .zip(rate.into_iter())
        .zip(call_put.into_iter())
        .map(
            |(((((s, sp), st), ty), r), cp)| match (s, sp, st, ty, r, cp) {
                (
                    Some(settle),
                    Some(s_val),
                    Some(k_val),
                    Some(t_val),
                    Some(r_val),
                    Some(cp_val),
                ) => {
                    let is_call = match cp_val {
                        "C" => true,
                        "P" => false,
                        _ => return None,
                    };
                    settlement_implied_volatility(settle, s_val, k_val, t_val, r_val, is_call)
                }
                _ => None,
            },
        )
        .collect();

    Ok(out.into_series())
}

#[pymodule]
fn stock_plugins(_py: Python, _m: &Bound<'_, PyModule>) -> PyResult<()> {
    Ok(())
}
