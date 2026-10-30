"""截面雷达数据新鲜度、时效衰减与价差补偿单测 (test_chemical_cross_section_freshness.py)。"""

from datetime import date

import polars as pl

from stock_analytics.marts.chemical_cross_section_mart import (
    CROSS_SECTION_SCHEMA,
    ChemicalCrossSectionMart,
)


def test_cross_section_schema_has_confidence() -> None:
    """验证 CROSS_SECTION_SCHEMA 包含 data_confidence_pct 字段契约。"""
    assert "data_confidence_pct" in CROSS_SECTION_SCHEMA
    assert CROSS_SECTION_SCHEMA["data_confidence_pct"] == pl.Float64


def test_cross_section_build_and_spread_derivation() -> None:
    """验证截面 Mart 端到端构建，理论价差 100% 覆盖且置信度有效。"""
    engine = ChemicalCrossSectionMart(as_of_date=date(2026, 9, 21))
    df = engine.build_cross_section_frame()
    assert len(df) == 13
    assert "data_confidence_pct" in df.columns

    # 验证 8 大品种全部覆盖理论价差 (非空)
    for row in df.iter_rows(named=True):
        code = row["commodity_code"]
        assert row["spread_margin_cny"] is not None, f"品种 {code} 理论价差为空"
        assert row["margin_regime"] not in ("unknown", ""), f"品种 {code} 利润相位未知"
        conf = row["data_confidence_pct"]
        assert 0.0 <= conf <= 100.0, f"品种 {code} 置信度异常: {conf}"

    # 验证补齐最新真实周报后，TA 与 V 置信度达到满分 100%，无过期滞后提示
    ta_row = df.filter(pl.col("commodity_code") == "TA").row(0, named=True)
    assert ta_row["data_confidence_pct"] == 100.0
    assert "过期" not in ta_row["key_rationale"]

    v_row = df.filter(pl.col("commodity_code") == "V").row(0, named=True)
    assert v_row["data_confidence_pct"] == 100.0
    assert "过期" not in v_row["key_rationale"]


def test_evaluate_cross_section_stale_isolation() -> None:
    """验证打分引擎对超过 30 天的数据自动进行时效隔离。"""
    engine = ChemicalCrossSectionMart(as_of_date=date(2026, 9, 21))
    # 模拟钛白粉 B 类寡头：若开工率为 2026-07-01 (滞后82天)，应触发过期隔离，退化为无开工状态
    phase, score, stance, rationale = engine._evaluate_cross_section(
        code="TiO2",
        name="钛白粉",
        category="B_oligopoly",
        spot_price=14200.0,
        marginal_cash_cost=13500.0,
        cash_coverage=100.0,
        cost_regime="marginal_loss",
        is_cash_breached=False,
        margin_regime="profitable",
        inv_stage="neutral_balanced",
        export_regime="stable",
        export_vol_yoy=3.7,
        alpha_leader="龙佰集团",
        operating_rate=70.0,
        factory_inv=None,
        operating_rate_asof_date=date(2026, 7, 1),  # 超过 30 天过期
        as_of_date=date(2026, 9, 21),
    )
    # 过期开工被隔离后，退化为缺周度数据状态，评分为 65.0 中性跟踪
    assert score == 65.0
    assert phase == "BALANCED"
    assert stance == "NEUTRAL_WATCH"
    assert "过期滞后" in rationale and "隔离打分" in rationale
