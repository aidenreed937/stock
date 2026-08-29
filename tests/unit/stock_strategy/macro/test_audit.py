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
                "标的/策略": "macro_rotation_v6",
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
        report_path=Path("dummy.md"),
        chart_path=None,
    )
    with pytest.raises(AssertionError, match="胜率退化"):
        assert_stability_guardrails(result)
