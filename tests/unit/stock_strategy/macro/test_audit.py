from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from stock_strategy.macro.audit import (
    StabilityAuditResult,
    assert_stability_guardrails,
)
from stock_strategy.macro.audit_calc import (
    compute_bear_regimes,
    compute_rolling_stats,
    compute_slice_metrics,
)


def test_compute_slice_metrics_normal() -> None:
    # 模拟 252 个交易日净值从 1.0 -> 1.10 (年化约 10%)
    dates = [date(2025, 1, 1)] * 252
    navs = [1.0 + i * (0.10 / 251) for i in range(252)]
    df = pl.DataFrame({"trade_date": dates, "test_strat": navs})

    metrics = compute_slice_metrics(df, ["test_strat"])
    res = metrics["test_strat"]
    assert res["total_return"] == pytest.approx(0.10, rel=1e-2)
    assert res["cagr"] == pytest.approx(0.10, rel=1e-2)
    assert res["max_drawdown"] == pytest.approx(0.0)


def test_compute_rolling_stats_shape() -> None:
    # 构造 300 个交易日的多策略宽表
    n = 300
    df = pl.DataFrame(
        {
            "trade_date": [date(2025, 1, 1)] * n,
            "中证全指": [1.0 + i * 0.001 for i in range(n)],
            "macro_rotation_v4": [1.0 + i * 0.002 for i in range(n)],
        }
    )
    res = compute_rolling_stats(df, window_days=252)
    assert len(res) == 2
    assert "跑赢基准(全指)概率" in res.columns
    # V4 收益始终高于全指，胜率应为 100%
    v4_row = res[res["标的/策略"] == "macro_rotation_v4"].iloc[0]
    assert v4_row["跑赢基准(全指)概率"] == 1.0


def test_assert_stability_guardrails_pass() -> None:
    rolling_df = pd.DataFrame(
        [
            {
                "标的/策略": "macro_rotation_v4",
                "滚动窗口": "756 交易日",
                "跑赢基准(全指)概率": 0.88,
            }
        ]
    )
    stress_df = pd.DataFrame(
        [
            {
                "标的/策略": "macro_rotation_v4",
                "压力测试情景": "2024 微盘流动性踩踏",
                "区间最深回撤": -0.06,
            }
        ]
    )
    result = StabilityAuditResult(
        wide_nav=pl.DataFrame(),
        regime_df=pd.DataFrame(),
        stress_df=stress_df,
        rolling_df=rolling_df,
        bear_df=pd.DataFrame(),
        report_path=Path("dummy.md"),
        chart_path=None,
    )
    # 应正常通过
    assert_stability_guardrails(result)


def test_assert_stability_guardrails_fail() -> None:
    rolling_df = pd.DataFrame(
        [
            {
                "标的/策略": "macro_rotation_v4",
                "滚动窗口": "756 交易日",
                "跑赢基准(全指)概率": 0.75,  # 低于 80%
            }
        ]
    )
    result = StabilityAuditResult(
        wide_nav=pl.DataFrame(),
        regime_df=pd.DataFrame(),
        stress_df=pd.DataFrame(),
        rolling_df=rolling_df,
        bear_df=pd.DataFrame(),
        report_path=Path("dummy.md"),
        chart_path=None,
    )
    with pytest.raises(AssertionError, match="胜率退化"):
        assert_stability_guardrails(result)


def test_compute_bear_regimes_price_engine() -> None:
    """价格引擎: 基准先涨后崩 (250日新高回撤 >20% 且持续 >=60 交易日) 应识别出熊市。"""
    n = 260
    dates = [date(2024, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(n)]
    bench = (
        [float(100 + i) for i in range(60)]  # 上涨建立 250 日峰值
        + [120.0 * (1 - 0.33 * (i / 149)) for i in range(150)]  # 从峰值回撤 33%
        + [80.0] * 50
    )
    df = pl.DataFrame({"trade_date": dates, "中证全指": bench, "macro_rotation_v5_etf": bench})
    res = compute_bear_regimes(df, risk_factors=None, cols=None, min_days=60)
    price_rows = res[res["识别引擎"].str.startswith("价格回撤")]
    assert not price_rows.empty
    # 应识别出 1 个熊市区间
    assert len(price_rows["熊市区间"].unique()) == 1


def test_compute_bear_regimes_factor_engine() -> None:
    """四低共振引擎: 估值/成交/杠杆/价格 四低中不足 3 项 (默认阈值) 时不应识别为熊市。"""
    n = 300
    dates = [date(2024, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(n)]
    # 价格先涨后高位横盘 (250 日滚动分位高, 不低), 仅估值/杠杆低 -> 不足 3 项共振
    bench = [float(100 + i) for i in range(200)] + [300.0] * 100
    wide = pl.DataFrame(
        {
            "trade_date": dates,
            "中证全指": bench,
            "macro_rotation_v5_etf": bench,
        }
    )
    risk = pl.DataFrame(
        {
            "trade_date": dates,
            "dim_leverage": [30.0] * 300,
            "dim_crowding": [50.0] * 300,
            "dim_valuation": [30.0] * 300,
        }
    )
    res = compute_bear_regimes(wide, risk_factors=risk, cols=None, min_days=45)
    if res.empty:
        assert True
    else:
        factor_rows = res[res["识别引擎"].str.startswith("四低共振")]
        assert factor_rows.empty


def test_compute_bear_regimes_factor_confirmed_by_price() -> None:
    """四低共振: 估值/成交/杠杆/价格 全部低位时应识别为熊市底部。"""
    n = 300
    dates = [date(2024, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(n)]
    # 价格持续下跌后处于 250 日区间底部 (价格分位低)
    bench = [float(100 - i * 0.2) for i in range(n)]
    wide = pl.DataFrame({"trade_date": dates, "中证全指": bench, "macro_rotation_v5_etf": bench})
    risk = pl.DataFrame(
        {
            "trade_date": dates,
            "dim_leverage": [30.0] * 300,
            "dim_crowding": [30.0] * 300,
            "dim_valuation": [30.0] * 300,
        }
    )
    res = compute_bear_regimes(wide, risk_factors=risk, cols=None, min_days=45)
    factor_rows = res[res["识别引擎"].str.startswith("四低共振")]
    assert not factor_rows.empty
    # 输出列齐全
    assert {"识别引擎", "熊市区间", "区间收益", "最深回撤", "回本所需交易日"}.issubset(res.columns)
