"""数据质量校验规则单元测试。"""

from datetime import date
import polars as pl
import pytest

from stock.data.validator.rules import (
    NullCheckRule,
    PrimaryKeyRule,
    OhlcLogicRule,
    VolatilityRule,
    CompletenessRule,
)


def test_null_check_rule() -> None:
    rule = NullCheckRule(columns=["close", "open"])
    df_pass = pl.DataFrame({"close": [10.0, 11.0], "open": [9.0, 10.0]})
    res_pass = rule.audit(df_pass)
    assert res_pass["passed"] is True
    assert res_pass["total_nulls"] == 0

    df_fail = pl.DataFrame({"close": [10.0, None], "open": [9.0, 10.0]})
    res_fail = rule.audit(df_fail)
    assert res_fail["passed"] is False
    assert res_fail["total_nulls"] == 1
    assert res_fail["null_details"]["close"] == 1


def test_primary_key_rule() -> None:
    rule = PrimaryKeyRule(keys=["symbol", "trade_date"])
    df_pass = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11)]
    })
    res_pass = rule.audit(df_pass)
    assert res_pass["passed"] is True
    assert res_pass["duplicate_records"] == 0

    df_fail = pl.DataFrame({
        "symbol": ["000001.SZ", "000001.SZ"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11)]
    })
    res_fail = rule.audit(df_fail)
    assert res_fail["passed"] is False
    assert res_fail["duplicate_records"] == 1


def test_ohlc_logic_rule() -> None:
    rule = OhlcLogicRule()
    # 正常数据
    df_pass = pl.DataFrame({
        "open": [10.0],
        "high": [10.5],
        "low": [9.5],
        "close": [10.2]
    })
    res_pass = rule.audit(df_pass)
    assert res_pass["passed"] is True
    assert res_pass["physical_errors"] == 0

    # 异常数据：high < low
    df_fail = pl.DataFrame({
        "open": [10.0],
        "high": [9.0],
        "low": [9.5],
        "close": [10.2]
    })
    res_fail = rule.audit(df_fail)
    assert res_fail["passed"] is False
    assert res_fail["physical_errors"] == 1


def test_volatility_rule() -> None:
    rule = VolatilityRule()
    # 正常数据
    df_pass = pl.DataFrame({
        "close": [10.5],
        "pre_close": [10.0],
        "pct_chg": [5.0],
        "turnover_rate": [5.0]
    })
    res_pass = rule.audit(df_pass)
    assert res_pass["passed"] is True
    assert res_pass["calc_diff_errors"] == 0
    assert res_pass["spike_faults"] == 0
    assert res_pass["turnover_faults"] == 0

    # 极端涨跌幅 (飞线)
    df_spike = pl.DataFrame({
        "close": [110.0],
        "pre_close": [10.0],
        "pct_chg": [1000.1],
        "turnover_rate": [5.0]
    })
    res_spike = rule.audit(df_spike)
    assert res_spike["passed"] is False
    assert res_spike["spike_faults"] == 1

    # 极端换手率 (溢出)
    df_turnover = pl.DataFrame({
        "close": [10.5],
        "pre_close": [10.0],
        "pct_chg": [5.0],
        "turnover_rate": [300.1]
    })
    res_turnover = rule.audit(df_turnover)
    assert res_turnover["passed"] is False
    assert res_turnover["turnover_faults"] == 1


def test_completeness_rule() -> None:
    rule = CompletenessRule(min_count=5, max_count=10)
    # 正常分布
    df_pass = pl.DataFrame({
        "trade_date": [date(2026, 8, 11)] * 6,
        "symbol": [f"S_{i}" for i in range(6)]
    })
    res_pass = rule.audit(df_pass)
    assert res_pass["passed"] is True
    assert res_pass["truncated_dates_count"] == 0
    assert res_pass["anomaly_dates_count"] == 0

    # 截断（数据过多）
    df_trunc = pl.DataFrame({
        "trade_date": [date(2026, 8, 11)] * 11,
        "symbol": [f"S_{i}" for i in range(11)]
    })
    res_trunc = rule.audit(df_trunc)
    assert res_trunc["passed"] is False
    assert res_trunc["truncated_dates_count"] == 1

    # 异常少数据
    df_low = pl.DataFrame({
        "trade_date": [date(2026, 8, 11)] * 3,
        "symbol": [f"S_{i}" for i in range(3)]
    })
    res_low = rule.audit(df_low)
    # 按原逻辑，数据少只会增加 anomaly_dates_count，不会导致 passed=False
    assert res_low["passed"] is True
    assert res_low["anomaly_dates_count"] == 1
