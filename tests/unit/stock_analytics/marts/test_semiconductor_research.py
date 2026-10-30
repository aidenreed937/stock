"""半导体产业深研统一面板 Mart（semiconductor_research_panel）单元测试。

覆盖：驱动源识别（driver_regime）、库存相态判定、库存分位、结构性腿滚动有效性标记、
季度→日频前向填充（release_date 无前视）、Mart 落盘与 schema 稳定性。
"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.marts.semiconductor_research import (
    SEMICONDUCTOR_RESEARCH_MART_NAME,
    SEMICONDUCTOR_RESEARCH_SCHEMA,
    _driver_regime,
    _full_sample_percentile,
    _memory_lead_regime,
    _quarterly_to_daily_forward,
    _regime_by_thresholds,
    _rolling_leg_active,
    _taiwan_lead_effective_date,
)


def test_driver_regime_downturn_when_global_negative() -> None:
    assert _driver_regime(-3.8, 19.3) == "downturn"
    assert _driver_regime(-1.0, None) == "downturn"


def test_driver_regime_ai_when_spread_high() -> None:
    assert _driver_regime(21.0, 40.2) == "ai_driven"


def test_driver_regime_broad_cycle_when_low_spread() -> None:
    # 2019-2021 缺芯轮分化 ≈0；2017-2018 存储轮 +15.7pp（与宽基不可分，诚实归入 broad_cycle）
    assert _driver_regime(20.8, 15.7) == "broad_cycle"
    assert _driver_regime(5.3, -1.6) == "broad_cycle"


def test_driver_regime_unknown_when_data_missing() -> None:
    assert _driver_regime(None, None) == "unknown"


def test_regime_by_thresholds_idm() -> None:
    assert _regime_by_thresholds(152.4, (150.0, 130.0, 105.0)) == "high_overstocked"
    assert _regime_by_thresholds(132.0, (150.0, 130.0, 105.0)) == "elevated_destocking"
    assert _regime_by_thresholds(110.0, (150.0, 130.0, 105.0)) == "normal_balanced"
    assert _regime_by_thresholds(90.0, (150.0, 130.0, 105.0)) == "tight_restocking"
    assert _regime_by_thresholds(None, (150.0, 130.0, 105.0)) is None


def test_full_sample_percentile_bounds() -> None:
    s = pl.Series([100.0, 150.0, 152.4, 80.0, 95.0])
    pct = _full_sample_percentile(s)
    # 152.4 是最大值 → 100；100 排第 3/5 → 50
    assert pct.to_list()[2] == 100.0
    assert abs(pct.to_list()[0] - 50.0) < 1e-9
    empty = _full_sample_percentile(pl.Series([None, None], dtype=pl.Float64))
    assert empty.to_list() == [None, None]


def test_full_sample_percentile_ties_share_min_rank() -> None:
    """并列值共享最小名次（quant-metric-standards 百分位排名标准）。"""
    pct = _full_sample_percentile(pl.Series([1.0, 2.0, 2.0, 3.0, 4.0]))
    assert pct.to_list() == [0.0, 25.0, 25.0, 75.0, 100.0]


def test_full_sample_percentile_preserves_null_positions() -> None:
    """缺失值原位保持，且去空后的并列语义仍为最小名次。"""
    pct = _full_sample_percentile(pl.Series([3.0, None, 2.0, 2.0]))
    assert pct.to_list() == [100.0, None, 0.0, 0.0]


def test_full_sample_percentile_single_sample_returns_missing() -> None:
    """N <= 1 时按规范返回缺失（不做 0.0 兜底）。"""
    assert _full_sample_percentile(pl.Series([7.0])).to_list() == [None]
    assert _full_sample_percentile(pl.Series([None])).to_list() == [None]
    assert _full_sample_percentile(pl.Series([None, 2.0])).to_list() == [None, None]


def test_quarterly_to_daily_forward_uses_release_date() -> None:
    calendar = pl.DataFrame(
        {"trade_date": [date(2024, 3, 1), date(2024, 4, 15), date(2024, 5, 1), date(2024, 7, 1)]}
    )
    quarterly = pl.DataFrame(
        {
            "report_quarter": ["2024Q1", "2024Q2"],
            "quarter_value": [85.0, 90.0],
            "release_date": [date(2024, 4, 10), date(2024, 7, 15)],
        }
    )
    out = _quarterly_to_daily_forward(quarterly, calendar)
    # 2024-03-01 无生效数据 → 空；04-15 起用 85（Q1 已发布）；07-01 仍 85（Q2 未发布）
    vals = dict(zip(out["trade_date"].to_list(), out["quarter_value"].to_list(), strict=False))
    assert vals[date(2024, 3, 1)] is None
    assert vals[date(2024, 4, 15)] == 85.0
    assert vals[date(2024, 5, 1)] == 85.0
    assert vals[date(2024, 7, 1)] == 85.0  # Q2 release 07-15 未到，无前视


def test_rolling_leg_active_positive_and_negative() -> None:
    # 构造腿分位与未来收益正相关 → tail active=True；反相关 → False
    n = 300
    import numpy as np

    rng = np.random.default_rng(42)
    ret = rng.normal(0, 0.01, n + 60)
    close = 100.0 * np.cumprod(1 + ret)
    leg_pos = pl.Series(np.linspace(10, 90, n))
    active = _rolling_leg_active(leg_pos, pl.Series(close.tolist()[:n]))
    assert bool(active[-1]) is True

    leg_neg = pl.Series(np.linspace(90, 10, n))
    active_neg = _rolling_leg_active(leg_neg, pl.Series(close.tolist()[:n]))
    assert bool(active_neg[-1]) is False


def test_rolling_leg_active_constant_input_returns_false() -> None:
    n = 200
    leg_const = pl.Series([100.0] * n, dtype=pl.Float64)
    close = pl.Series([100.0 + i * 0.01 for i in range(n)])
    out = _rolling_leg_active(leg_const, close, window=100, fwd_days=10, min_samples=30)
    assert out.to_list()[-1] is False


def test_memory_lead_regime_classification() -> None:
    # 顶背离预警: 原厂高热但模组骤冷
    assert _memory_lead_regime(25.0, -5.0) == "bull_divergence"
    # 强扩张: 双方高增
    assert _memory_lead_regime(22.0, 18.0) == "strong_expansion"
    # 渠道抢跑: 模组率先放量
    assert _memory_lead_regime(5.0, 20.0) == "channel_frontrun"
    # 下行收缩: 双双转负
    assert _memory_lead_regime(-10.0, -15.0) == "contraction"
    # 平稳中性
    assert _memory_lead_regime(8.0, 10.0) == "neutral"
    # 缺失
    assert _memory_lead_regime(None, None) == "unknown"


def test_taiwan_lead_effective_date_prevents_lookahead() -> None:
    # 有明确 release_date 时优先采用
    assert _taiwan_lead_effective_date("2024-01", date(2024, 2, 7)) == date(2024, 2, 7)
    # 无 release_date 时严格按次月 10 日生效，杜绝未来信息
    assert _taiwan_lead_effective_date("2024-01", None) == date(2024, 2, 10)
    # 跨年次月 10 日
    assert _taiwan_lead_effective_date("2024-12", None) == date(2025, 1, 10)


def test_schema_stable_and_mart_name() -> None:
    assert SEMICONDUCTOR_RESEARCH_MART_NAME == "semiconductor_research_panel"
    assert "trade_date" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "industry_code" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "driver_regime" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "ai_capex_leg_active" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "defense_trigger" in SEMICONDUCTOR_RESEARCH_SCHEMA
    # 验证 P2 存储先导动能特征
    assert "nanya_revenue_yoy" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "adata_revenue_yoy" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "memory_lead_yoy" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "memory_module_idm_spread" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert "memory_lead_regime" in SEMICONDUCTOR_RESEARCH_SCHEMA
    assert SEMICONDUCTOR_RESEARCH_SCHEMA["driver_regime"] == pl.Utf8
    assert SEMICONDUCTOR_RESEARCH_SCHEMA["ai_capex_leg_active"] == pl.Boolean
    assert SEMICONDUCTOR_RESEARCH_SCHEMA["memory_lead_regime"] == pl.Utf8
