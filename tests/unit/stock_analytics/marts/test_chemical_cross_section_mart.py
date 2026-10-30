"""化工大宗周期多品种横向截面 Mart (chemical_cross_section_mart) 单元测试。

覆盖：
1. 8 大子品种元数据与交易门禁配置加载；
2. 周期相位判定引擎 (_evaluate_cross_section) 与评分规则；
3. 截面快照构建、完整性与 Schema 契约验证；
4. ASCII 投研雷达大表格式化输出验证。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.marts.chemical_cross_section_mart import (
    COMMODITY_SPECS,
    ChemicalCrossSectionMart,
    format_cross_section_table,
)


def test_commodity_specs_coverage() -> None:
    """验证 13 大子品种元数据配置完整性。"""
    assert len(COMMODITY_SPECS) == 13
    codes = [spec["code"] for spec in COMMODITY_SPECS]
    assert codes == [
        "SA",
        "TA",
        "MEG",
        "MA",
        "V",
        "TiO2",
        "MDI",
        "R32",
        "UR",
        "SH",
        "EB",
        "PP",
        "PX",
    ]

    for spec in COMMODITY_SPECS:
        submodule = spec["submodule"]
        config_path = Path(f"config/industry/chemicals/{submodule}/trading_gates.yaml")
        assert config_path.exists(), f"配置目录缺失: {config_path}"


def test_cycle_phase_and_score_evaluation() -> None:
    """测试周期相位推断与打分逻辑边界。"""
    engine = ChemicalCrossSectionMart()

    # 1. 配额管控型品种 (制冷剂): 刚性供给 + 外需景气 -> OVERWEIGHT_RIGHT
    phase_quota, score_quota, stance_quota, rationale_quota = engine._evaluate_cross_section(
        code="R32",
        name="制冷剂R32",
        category="C_quota_regulated",
        spot_price=36000.0,
        marginal_cash_cost=20000.0,
        cash_coverage=180.0,
        cost_regime="super_profit",
        is_cash_breached=False,
        margin_regime="super_profit",
        inv_stage="active_restocking",
        export_regime="price_driven",
        export_vol_yoy=15.0,
        alpha_leader="巨化股份",
    )
    assert phase_quota == "RIGHT_EXPANSION"
    assert score_quota >= 90.0
    assert stance_quota == "OVERWEIGHT_RIGHT"
    assert "巨化股份" in rationale_quota

    # 2. 跌破边际现金成本底线 (纯碱/PVC) -> OVERWEIGHT_LEFT, 高赔率极值大底
    phase_bottom, score_bottom, stance_bottom, rationale_bottom = engine._evaluate_cross_section(
        code="SA",
        name="纯碱",
        category="A_commodity_futures",
        spot_price=1077.0,
        marginal_cash_cost=1550.0,
        cash_coverage=69.5,
        cost_regime="deep_cash_drain_bottom",
        is_cash_breached=True,
        margin_regime="cash_loss",
        inv_stage="active_destocking",
        export_regime="neutral_flat",
        export_vol_yoy=0.0,
        alpha_leader="远兴能源",
    )
    assert phase_bottom == "LEFT_BOTTOM"
    assert score_bottom >= 80.0
    assert stance_bottom == "OVERWEIGHT_LEFT"
    assert "跌破" in rationale_bottom or "现金保本底线" in rationale_bottom

    # 3. 暴利区间警惕高位钝化 (PEAK_OVERHEAT)
    phase_peak, score_peak, stance_peak, _ = engine._evaluate_cross_section(
        code="TA",
        name="精对苯二甲酸",
        category="A_commodity_futures",
        spot_price=8000.0,
        marginal_cash_cost=5000.0,
        cash_coverage=160.0,
        cost_regime="super_profit",
        is_cash_breached=False,
        margin_regime="super_profit",
        inv_stage="active_restocking",
        export_regime="neutral_flat",
        export_vol_yoy=-5.0,
        alpha_leader="恒力石化",
    )
    assert phase_peak == "PEAK_OVERHEAT"
    assert score_peak < 50.0
    assert stance_peak == "UNDERWEIGHT_TRIM"

    # 4. 现货价格缺失守卫 (P1 守卫): spot_price <= 0 -> DATA_INCOMPLETE, NEUTRAL_WATCH (50分)
    phase_zero, score_zero, stance_zero, rat_zero = engine._evaluate_cross_section(
        code="R32",
        name="制冷剂R32",
        category="C_quota_regulated",
        spot_price=0.0,
        marginal_cash_cost=None,
        cash_coverage=None,
        cost_regime="unknown",
        is_cash_breached=False,
        margin_regime="unknown",
        inv_stage="neutral_balanced",
        export_regime="price_driven",
        export_vol_yoy=-40.0,
        alpha_leader="巨化股份",
    )
    assert phase_zero == "DATA_INCOMPLETE"
    assert score_zero == 50.0
    assert stance_zero == "NEUTRAL_WATCH"
    assert "[数据缺失]" in rat_zero

    # 5. C类配额管制型但缺失成本模型: 降级折价至 75 分并标注维度不完整
    _, score_c_nocost, _, rat_c_nocost = engine._evaluate_cross_section(
        code="R32",
        name="制冷剂R32",
        category="C_quota_regulated",
        spot_price=36000.0,
        marginal_cash_cost=None,
        cash_coverage=None,
        cost_regime="unknown",
        is_cash_breached=False,
        margin_regime="unknown",
        inv_stage="neutral_balanced",
        export_regime="price_driven",
        export_vol_yoy=-40.0,
        alpha_leader="巨化股份",
    )
    assert score_c_nocost == 75.0
    assert "[维度不完整: 缺成本模型]" in rat_c_nocost

    # 6. B类寡头中游但缺失成本模型与周度库存开工: 降级至 65 分中性观察
    _, score_b_nocost, stance_b_nocost, rat_b_nocost = engine._evaluate_cross_section(
        code="MDI",
        name="聚合MDI",
        category="B_oligopoly",
        spot_price=18466.0,
        marginal_cash_cost=None,
        cash_coverage=None,
        cost_regime="unknown",
        is_cash_breached=False,
        margin_regime="unknown",
        inv_stage="neutral_balanced",
        export_regime="stable",
        export_vol_yoy=4.47,
        alpha_leader="万华化学",
    )
    assert score_b_nocost == 65.0
    assert stance_b_nocost == "NEUTRAL_WATCH"
    assert "[维度不完整: 缺成本曲线与开工库存]" in rat_b_nocost

    # 7. 滞后警告传递 (P3/P4)
    _, _, _, rat_stale = engine._evaluate_cross_section(
        code="TA",
        name="精对苯二甲酸",
        category="A_commodity_futures",
        spot_price=5000.0,
        marginal_cash_cost=4500.0,
        cash_coverage=110.0,
        cost_regime="normal",
        is_cash_breached=False,
        margin_regime="normal",
        inv_stage="neutral_balanced",
        export_regime="stable",
        export_vol_yoy=0.0,
        alpha_leader="恒力石化",
        stale_warnings=["企业库存取自2026-06-12(滞后100天)"],
    )
    assert "[数据滞后提示: 企业库存取自2026-06-12(滞后100天)]" in rat_stale

    # 8. B类寡头中游具备成本模型但缺失周度库存开工: 消除乐观偏误，限制在 65 分中性观察
    _, score_b_nosurvey, stance_b_nosurvey, rat_b_nosurvey = engine._evaluate_cross_section(
        code="TiO2",
        name="钛白粉",
        category="B_oligopoly",
        spot_price=14200.0,
        marginal_cash_cost=13500.0,
        cash_coverage=100.0,
        cost_regime="normal_profit",
        is_cash_breached=False,
        margin_regime="normal",
        inv_stage="neutral_balanced",
        export_regime="stable",
        export_vol_yoy=3.71,
        alpha_leader="龙佰集团",
        operating_rate=None,
        factory_inv=None,
    )
    assert score_b_nosurvey == 65.0
    assert stance_b_nosurvey == "NEUTRAL_WATCH"
    assert "[维度不完整: 缺周度开工与企业库存]" in rat_b_nosurvey


def test_cross_section_mart_build_real() -> None:
    """验证截面构建器生成有效 DataFrame，包含 13 大品种完整字段与正确排序。"""
    engine = ChemicalCrossSectionMart()
    df = engine.build_cross_section_frame()

    assert isinstance(df, pl.DataFrame)
    assert len(df) == 13
    assert "cross_section_rank" in df.columns
    assert "composite_score" in df.columns
    assert "investment_stance" in df.columns
    assert "alpha_leader_name" in df.columns
    assert "top_elastic_stock_name" in df.columns

    # 验证排名单调递增从 1 到 13
    ranks = df["cross_section_rank"].to_list()
    assert ranks == list(range(1, 14))

    # 验证打分降序排列
    scores = df["composite_score"].to_list()
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    # 验证真实有数据品种现货价格大于 0，且 R32 真实价格接入
    spot_dict = dict(zip(df["commodity_code"].to_list(), df["spot_price_cny"].to_list()))
    for c in ["SA", "TA", "MEG", "MA", "V", "TiO2", "MDI", "R32", "UR", "SH", "EB", "PP", "PX"]:
        assert spot_dict[c] is not None and spot_dict[c] > 0.0, f"品种 {c} 缺失真实价格"
    assert spot_dict["R32"] == 65000.0, "R32 应正确接入 100ppi 现货基准价"

    # 验证输出 ASCII 表格渲染
    table_text = format_cross_section_table(df)
    assert "大宗化工全板块多品种横向截面景气度与配置雷达" in table_text
    assert "纯碱" in table_text
    assert "制冷剂R32" in table_text
    assert "排名" in table_text
