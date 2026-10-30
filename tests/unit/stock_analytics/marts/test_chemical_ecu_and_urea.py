"""尿素 (UR) 农化启动与烧碱 (SH) 氯碱 ECU 闭环专项单测 (test_chemical_ecu_and_urea.py)。"""

from datetime import date

import polars as pl

from stock_analytics.marts.chemical_cost_curves import build_chemical_cost_curves_mart
from stock_analytics.marts.chemical_cross_section_mart import (
    COMMODITY_SPECS,
    ChemicalCrossSectionMart,
)
from stock_analytics.marts.chemical_elasticity_mart import build_chemical_elasticity_mart
from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator


def test_commodity_specs_expanded_to_10() -> None:
    """验证 COMMODITY_SPECS 扩充且包含 UR 与 SH。"""
    codes = [c["code"] for c in COMMODITY_SPECS]
    assert len(codes) >= 10
    assert "UR" in codes
    assert "SH" in codes

    ur_spec = next(c for c in COMMODITY_SPECS if c["code"] == "UR")
    assert ur_spec["name"] == "尿素"
    assert ur_spec["futures_symbol"] == "UR"
    assert ur_spec["category"] == "A_commodity_futures"

    sh_spec = next(c for c in COMMODITY_SPECS if c["code"] == "SH")
    assert sh_spec["name"] == "烧碱"
    assert sh_spec["futures_symbol"] == "SH"
    assert sh_spec["category"] == "A_commodity_futures"


def test_ecu_margin_calculation() -> None:
    """验证氯碱电化学单元 (ECU) 综合毛利与利润相位计算。"""
    calc = ChemicalSpreadCalculator(raw_dir="data/raw/industry")

    # 1. 模拟 32% 液碱 640 元/吨 (折百 2000 元/吨)，液氯平水 (0 元/吨)
    res = calc.calculate_ecu_margin(
        caustic_soda_price=640.0, chlorine_price=0.0, is_32pct_liquid=True
    )
    assert res["caustic_100_price"] == 2000.0
    assert res["ecu_revenue"] == 2000.0
    assert res["ecu_margin_cny"] == -200.0
    assert res["ecu_regime"] == "deep_loss"
    assert not res["is_cash_breached"]  # 2000 > cash_cost(1800)

    # 2. 模拟高景气情景：32% 液碱 800 元/吨 (折百 2500 元/吨)，液氯 300 元/吨
    res_boom = calc.calculate_ecu_margin(
        caustic_soda_price=800.0, chlorine_price=300.0, is_32pct_liquid=True
    )
    assert res_boom["caustic_100_price"] == 2500.0
    # 收入 = 2500 + 0.886 * 300 = 2765.8
    assert res_boom["ecu_revenue"] == 2765.8
    assert res_boom["ecu_margin_cny"] == 565.8
    assert res_boom["ecu_regime"] == "high_profit"


def test_urea_coal_margin_calculation() -> None:
    """验证煤制尿素加工差计算与利润相位判定。"""
    calc = ChemicalSpreadCalculator(raw_dir="data/raw/industry")

    # 模拟尿素现货 1800 元/吨，动力煤 750 元/吨
    res = calc.calculate_urea_coal_margin(urea_price=1800.0, thermal_coal_price=750.0)
    # cost_baseline = 1.2 * 750 + 450 = 1350
    assert res["cost_baseline"] == 1350.0
    assert res["spread_margin_cny"] == 450.0
    assert res["margin_regime"] == "high_profit"
    assert not res["is_cash_breached"]


def test_cost_curves_includes_ur_and_sh() -> None:
    """验证成本曲线 Mart 涵盖 UR 和 SH，且现货折百换算正确。"""
    summary_df, _ladder_df = build_chemical_cost_curves_mart()
    assert len(summary_df) >= 10
    codes = summary_df["commodity_code"].to_list()
    assert "UR" in codes
    assert "SH" in codes

    sh_row = summary_df.filter(pl.col("commodity_code") == "SH").row(0, named=True)
    # 现货 637 元/吨折百后应大于 1900 元/吨
    assert sh_row["spot_price_cny"] > 1900.0
    assert sh_row["marginal_cash_cost_cny"] == 1700.0
    assert sh_row["cash_cost_coverage_pct"] == 100.0

    ur_row = summary_df.filter(pl.col("commodity_code") == "UR").row(0, named=True)
    assert ur_row["spot_price_cny"] == 1802.5
    assert ur_row["marginal_cash_cost_cny"] == 1750.0
    assert ur_row["cash_cost_coverage_pct"] == 100.0


def test_elasticity_includes_ur_and_sh() -> None:
    """验证业绩弹性 Mart 包含 UR 和 SH 核心标的。"""
    df = build_chemical_elasticity_mart()
    assert len(df) >= 45
    codes = df["commodity_code"].unique().to_list()
    assert "UR" in codes
    assert "SH" in codes

    ur_stocks = df.filter(pl.col("commodity_code") == "UR")["company_name"].to_list()
    assert "华鲁恒升" in ur_stocks
    assert "阳煤化工" in ur_stocks

    sh_stocks = df.filter(pl.col("commodity_code") == "SH")["company_name"].to_list()
    assert "中盐化工" in sh_stocks
    assert "氯碱化工" in sh_stocks


def test_cross_section_mart_ecu_linkage_and_build() -> None:
    """验证截面雷达端到端构建且包含 ECU 氯碱闭环双向联动说明。"""
    engine = ChemicalCrossSectionMart(as_of_date=date(2026, 9, 21))
    df = engine.build_cross_section_frame()
    assert len(df) >= 10

    # 验证 10 个品种均有有效理论价差与置信度
    for row in df.iter_rows(named=True):
        code = row["commodity_code"]
        assert row["spot_price_cny"] > 0.0, f"品种 {code} 现货价为空"
        assert row["spread_margin_cny"] is not None, f"品种 {code} 理论价差为空"
        assert row["data_confidence_pct"] > 0.0, f"品种 {code} 置信度异常"

    # 验证 PVC 与烧碱的 ECU 联动注入
    v_row = df.filter(pl.col("commodity_code") == "V").row(0, named=True)
    assert "氯碱ECU平衡" in v_row["key_rationale"]
    assert "以碱补氯" in v_row["key_rationale"]

    sh_row = df.filter(pl.col("commodity_code") == "SH").row(0, named=True)
    assert "氯碱ECU平衡" in sh_row["key_rationale"]
    assert "副产氯气" in sh_row["key_rationale"]
