"""因子工程与特征库算子单元测试。"""

from datetime import date

import polars as pl

from stock.analytics.features.factors import FactorEngine
from stock.analytics.primitives import (
    calculate_amihud_illiquidity,
    calculate_atr,
    calculate_bollinger_bandwidth,
    calculate_distance_to_high,
    calculate_ema_spread,
    calculate_equity_risk_premium,
    calculate_main_moneyflow_factors,
    calculate_margin_factors,
    calculate_momentum,
    calculate_realized_volatility,
    calculate_rolling_percentile,
    calculate_short_term_reversal,
    calculate_turnover_factors,
    calculate_volume_surprise,
    calculate_yield_curve_slope,
)


def _create_sample_ohlcv(n: int = 50) -> pl.DataFrame:
    """构造基础测试用面板行情数据。"""
    dates = [date(2026, 1, 1) for _ in range(n)]
    prices = [10.0 + i * 0.2 for i in range(n)]
    return pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["000001.SZ"] * n,
            "open": [p - 0.1 for p in prices],
            "high": [p + 0.3 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [10000.0 + i * 100 for i in range(n)],
            "amount": [(10.0 + i * 0.2) * (10000.0 + i * 100) for i in range(n)],
            "turnover_rate": [1.5 + (i % 5) * 0.2 for i in range(n)],
            "net_mf_amount": [5000.0 * (1 if i % 2 == 0 else -1) for i in range(n)],
            "pe_ttm": [15.0 + (i % 10) * 0.5 for i in range(n)],
            "pb": [1.8 + (i % 8) * 0.1 for i in range(n)],
        }
    )


def test_momentum_factors() -> None:
    df = _create_sample_ohlcv(60)
    res = calculate_momentum(df, windows=(5, 20))
    assert "mom_5d" in res.columns
    assert "mom_20d" in res.columns
    assert res["mom_5d"][-1] is not None
    assert res["mom_5d"][-1] > 0

    res_rev = calculate_short_term_reversal(df, window=5)
    assert "reversal_5d" in res_rev.columns
    assert res_rev["reversal_5d"][-1] < 0  # 价格上涨时反转因子为负

    res_high = calculate_distance_to_high(df, window=20)
    assert "dist_to_high_20d" in res_high.columns
    assert res_high["dist_to_high_20d"][-1] == 0.0  # 单调递增时收盘价即为最高价

    res_ema = calculate_ema_spread(df, fast=5, slow=20)
    assert "ema_spread_5_20" in res_ema.columns
    assert res_ema["ema_spread_5_20"][-1] > 0


def test_volatility_factors() -> None:
    df = _create_sample_ohlcv(50)
    res_vol = calculate_realized_volatility(df, windows=(10, 20))
    assert "realized_vol_10d" in res_vol.columns
    assert "realized_vol_20d" in res_vol.columns
    assert res_vol["realized_vol_20d"][-1] > 0

    res_atr = calculate_atr(df, window=10)
    assert "atr_10d" in res_atr.columns
    assert "atr_ratio_10d" in res_atr.columns
    assert res_atr["atr_10d"][-1] > 0

    res_bb = calculate_bollinger_bandwidth(df, window=10)
    assert "bollinger_bandwidth_10d" in res_bb.columns
    assert res_bb["bollinger_bandwidth_10d"][-1] > 0


def test_liquidity_factors() -> None:
    df = _create_sample_ohlcv(50)
    res_illiq = calculate_amihud_illiquidity(df, window=10)
    assert "amihud_illiq_10d" in res_illiq.columns
    assert res_illiq["amihud_illiq_10d"][-1] >= 0

    res_to = calculate_turnover_factors(df, window=10)
    assert "turnover_mean_10d" in res_to.columns
    assert "turnover_std_10d" in res_to.columns

    res_vs = calculate_volume_surprise(df, short_window=5, long_window=20)
    assert "volume_surprise_5_20" in res_vs.columns


def test_moneyflow_and_margin_factors() -> None:
    df = _create_sample_ohlcv(50)
    res_mf = calculate_main_moneyflow_factors(df, windows=(5, 10))
    assert "main_inflow_ratio" in res_mf.columns
    assert "main_inflow_ratio_5d" in res_mf.columns

    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)] * 30,
            "symbol": ["000001.SZ"] * 30,
            "amount": [1e8] * 30,
            "rzmre": [8e6] * 30,
            "rzrqye": [1e9 + i * 1e7 for i in range(30)],
        }
    )
    res_margin = calculate_margin_factors(margin_df, windows=(5, 10))
    assert "margin_trading_share" in res_margin.columns
    assert "margin_growth_5d" in res_margin.columns
    assert abs(res_margin["margin_trading_share"][0] - 0.08) < 1e-4


def test_valuation_and_macro_factors() -> None:
    df = _create_sample_ohlcv(60)
    res_pct = calculate_rolling_percentile(df, metric_cols=("pe_ttm", "pb"), window_days=20)
    assert "pe_ttm_percentile_20d" in res_pct.columns
    assert "pb_percentile_20d" in res_pct.columns

    macro_df = pl.DataFrame(
        {
            "pe_ttm": [20.0, 25.0],
            "cn_10y_bond_yield": [2.5, 2.3],
            "t10y": [4.2, 4.3],
            "t2y": [3.8, 3.9],
        }
    )
    res_erp = calculate_equity_risk_premium(macro_df)
    assert "equity_risk_premium" in res_erp.columns
    # 1/20 * 100 - 2.5 = 2.5%
    assert abs(res_erp["equity_risk_premium"][0] - 2.5) < 1e-3

    res_slope = calculate_yield_curve_slope(macro_df)
    assert "yield_curve_slope_10y_2y" in res_slope.columns
    assert abs(res_slope["yield_curve_slope_10y_2y"][0] - 0.4) < 1e-3


def test_factor_engine_all_and_normalization() -> None:
    df = _create_sample_ohlcv(60)
    all_factors = FactorEngine.compute_all_factors(df, normalize=True)
    assert "mom_20d" in all_factors.columns
    assert "realized_vol_20d" in all_factors.columns
    assert "amihud_illiq_20d" in all_factors.columns
    assert "mom_20d_zscore" in all_factors.columns


def test_empty_dataframe_safety() -> None:
    empty_df = pl.DataFrame()
    assert calculate_momentum(empty_df).is_empty()
    assert calculate_realized_volatility(empty_df).is_empty()
    assert calculate_amihud_illiquidity(empty_df).is_empty()
    assert calculate_main_moneyflow_factors(empty_df).is_empty()
    assert calculate_rolling_percentile(empty_df).is_empty()
    assert FactorEngine.compute_all_factors(empty_df).is_empty()
