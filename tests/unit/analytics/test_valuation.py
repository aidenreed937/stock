from datetime import date

import polars as pl

from stock.analytics.primitives.valuation import (
    calculate_index_valuation_summary,
    calculate_valuation_percentile,
)


def test_calculate_valuation_percentile_empty():
    df = pl.DataFrame()
    assert calculate_valuation_percentile(df) == {}


def test_calculate_valuation_percentile_missing_columns():
    df = pl.DataFrame({"trade_date": ["2026-08-01"]})
    assert calculate_valuation_percentile(df, metric_col="pe") == {}


def test_calculate_valuation_percentile_normal():
    # 生成 10 个测试点位 (10..100)
    dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
    closes = [float(i * 10) for i in range(1, 11)]  # 最新为 100 (100% 分位 -> EXTREME_HIGH)
    df = pl.DataFrame({"trade_date": dates, "close": closes})

    res = calculate_valuation_percentile(df, metric_col="close", window_years=10)
    assert res["current_value"] == 100.0
    assert res["min_value"] == 10.0
    assert res["max_value"] == 100.0
    assert res["percentile_rank"] == 100.0
    assert res["zone"] == "EXTREME_HIGH"
    assert res["multiplier"] == 0.0


def test_calculate_valuation_percentile_extreme_low():
    # 最新处于最低点 (10% 分位 -> EXTREME_LOW)
    dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
    closes = [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    df = pl.DataFrame({"trade_date": dates, "close": closes})

    res = calculate_valuation_percentile(df, metric_col="close", window_years=10)
    assert res["percentile_rank"] == 10.0
    assert res["zone"] == "LOW"
    assert res["multiplier"] == 1.5


def test_calculate_valuation_percentile_inverse():
    # 反向指标股息率 dv_ratio (越高越低估)
    dates = [f"2026-08-{i:02d}" for i in range(1, 11)]
    dv_ratios = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]  # 最新为 10% 股息率 (极度低估)
    df = pl.DataFrame({"trade_date": dates, "dv_ratio": dv_ratios})

    res = calculate_valuation_percentile(df, metric_col="dv_ratio", window_years=10)
    assert res["is_inverse"] is True
    assert res["percentile_rank"] == 10.0
    assert res["zone"] == "LOW"
    assert res["multiplier"] == 1.5


def test_calculate_index_valuation_summary():
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, i) for i in range(1, 11)],
            "pe_ttm": [15.0] * 10,
            "close": [3000.0] * 10,
        }
    )
    res = calculate_index_valuation_summary(df, symbol="000300.SH")
    assert res["symbol"] == "000300.SH"
    assert "pe_ttm" in res["evaluations"]
    assert "close" in res["evaluations"]
