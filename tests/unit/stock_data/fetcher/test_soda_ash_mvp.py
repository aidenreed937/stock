"""纯碱 (Soda Ash / SA) 最小可行闭环 (MVP) 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from scripts.soda_ash_mvp_pipeline import (
    SodaAshMvpPipeline,
    calculate_implied_shipment_rate,
)

from stock_data.fetcher.industry.chemicals.collectors.spreads import (
    ChemicalSpreadCalculator,
)


def test_chemical_cost_models_yaml_valid():
    """测试纯碱品种级成本模型配置文件合法性与关键工艺齐全性。"""
    cfg_path = Path("config/industry/chemicals/soda_ash/cost_models.yaml")
    assert cfg_path.exists(), "soda_ash/cost_models.yaml 必须存在"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "models" in data
    assert "hou_process" in data["models"]
    assert "solvay_process" in data["models"]
    assert "natural_alkali" in data["models"]

    hou = data["models"]["hou_process"]
    assert hou["coefficients"]["raw_salt"] == 1.2
    assert hou["fixed_cost"] > 0

    thresholds = data.get("regime_thresholds", {})
    assert "high_profit" in thresholds
    assert "near_breakeven" in thresholds


def test_soda_ash_capacity_projects_yaml_valid():
    """测试纯碱重大产能事件种子库合法性。"""
    p_path = Path("config/industry/chemicals/soda_ash/capacity_projects.yaml")
    assert p_path.exists(), "soda_ash/capacity_projects.yaml 必须存在"
    data = yaml.safe_load(p_path.read_text(encoding="utf-8"))
    assert "projects" in data
    projects = data["projects"]
    assert len(projects) >= 5

    # 必须包含远兴阿拉善天然碱项目
    yx_projects = [p for p in projects if "远兴能源" in p["company"]]
    assert len(yx_projects) >= 4
    total_yx_cap = sum(p["capacity_w_tons"] for p in yx_projects)
    assert total_yx_cap >= 500.0


def test_cyclical_trading_gates_yaml_valid():
    """测试各化工子模块分阶段量化交易门禁配置合法性。"""
    soda_path = Path("config/industry/chemicals/soda_ash/trading_gates.yaml")
    poly_path = Path("config/industry/chemicals/polyurethane/trading_gates.yaml")
    refr_path = Path("config/industry/chemicals/refrigerant/trading_gates.yaml")

    assert soda_path.exists(), "soda_ash/trading_gates.yaml 必须存在"
    assert poly_path.exists(), "polyurethane/trading_gates.yaml 必须存在"
    assert refr_path.exists(), "refrigerant/trading_gates.yaml 必须存在"

    soda_cfg = yaml.safe_load(soda_path.read_text(encoding="utf-8"))
    poly_cfg = yaml.safe_load(poly_path.read_text(encoding="utf-8"))
    refr_cfg = yaml.safe_load(refr_path.read_text(encoding="utf-8"))

    # 校验三元分类特色逻辑
    # 1. 寡头品允许更高 PE 见顶 (14.0 vs 8.0)
    assert poly_cfg["top_escape"]["rules"]["pe_ttm_low_trap_max"] == 14.0
    # 2. 配额品切断超额暴利扩产逃顶分支
    assert refr_cfg["top_escape"]["ignore_capex_high_profit_feedback"] is True

    # 3. 纯碱标准大宗三门禁完备
    gates = soda_cfg
    assert "left_side_odds" in gates
    assert "right_side_confirmation" in gates
    assert "top_escape" in gates

    # 1. 左侧门禁校验
    left = gates["left_side_odds"]
    assert left["target_position_pct_max"] <= 35.0
    assert "margin_regime_any" in left["rules"]
    assert "pb_percentile_10y_max" in left["rules"]

    # 2. 右侧门禁校验
    right = gates["right_side_confirmation"]
    assert right["rules"]["operating_rate_max"] <= 0.80
    assert right["rules"]["destocking_weeks_min"] >= 2
    assert "basis_rate_min" in right["rules"]

    # 3. 逃顶门禁校验
    top = gates["top_escape"]
    assert top["action"] == "clear_position"
    assert top["rules"]["operating_rate_min"] >= 0.85
    assert "pe_ttm_low_trap_max" in top["rules"]

    # 4. 标的角色池校验 (品种级唯一维护源)
    product_data = yaml.safe_load(
        Path("config/industry/chemicals/soda_ash/trading_gates.yaml").read_text(encoding="utf-8")
    )
    assert "target_universe_mapping" in product_data
    mapping = product_data["target_universe_mapping"]
    assert "alpha_leader" in mapping
    assert "beta_elastic" in mapping
    assert any(c["symbol"] == "000683.SZ" for c in mapping["alpha_leader"])
    assert any(c["symbol"] == "600328.SH" for c in mapping["beta_elastic"])


def test_chemical_spread_calculator_config_driven():
    """测试配置驱动的纯碱双吨利润与氨碱法现金成本计算。"""
    calc = ChemicalSpreadCalculator(
        raw_dir="data/raw/industry/chemicals",
        config_path="config/industry/chemicals/soda_ash/cost_models.yaml",
    )
    models = calc.load_cost_models()
    assert "models" in models

    # 1. 联碱双吨利润测试
    # 纯碱=1500, 氯化铵=480, 原盐=250, 合成氨=2800, 动力煤=800, 固定加工费默认 450
    # 理论毛利 = (1500 + 480) - (1.2*250 + 0.135*2800 + 0.4*800) - 450
    # raw_cost = 300 + 378 + 320 = 998
    # margin = 1980 - 998 - 450 = 532.0 (超额暴利)
    margin = calc.calculate_soda_ash_double_ton_margin(
        soda_price=1500.0,
        nh4cl_price=480.0,
        salt_price=250.0,
        nh3_price=2800.0,
        coal_price=800.0,
    )
    assert margin == 532.0
    assert calc.get_margin_regime(margin) == "high_profit"

    # 2. 深度亏损状态测试
    loss_margin = calc.calculate_soda_ash_double_ton_margin(
        soda_price=1000.0,
        nh4cl_price=250.0,
        salt_price=300.0,
        nh3_price=3200.0,
        coal_price=900.0,
    )
    assert loss_margin < -150.0
    assert calc.get_margin_regime(loss_margin) == "deep_loss"

    # 3. 氨碱法现金成本测试
    cash_cost = calc.calculate_soda_ash_solvay_cash_cost(
        salt_price=250.0,
        limestone_price=60.0,
        coal_price=800.0,
        coke_price=1500.0,
    )
    # 1.5*250 + 1.3*60 + 0.35*800 + 0.12*1500 + 260 = 375 + 78 + 280 + 180 + 260 = 1173.0
    assert cash_cost == 1173.0


def test_calculate_implied_shipment_rate():
    """测试基于物理物料守恒公式推导周度产销率。"""
    # 1. 正常去库场景: 周产 74.58 万吨，厂库从 185.67 去至 184.49 (去库 1.18 万吨)
    # 隐含出货 = 74.58 - (-1.18) = 75.76，产销率 = 75.76 / 74.58 = 101.58%
    rate_destock = calculate_implied_shipment_rate(
        weekly_output=74.58,
        current_inv=184.49,
        prev_inv=185.67,
    )
    assert rate_destock == 101.58

    # 2. 正常累库场景: 周产 71.88 万吨，厂库从 187.27 累至 191.13 (累库 3.86 万吨)
    # 隐含出货 = 71.88 - 3.86 = 68.02，产销率 = 68.02 / 71.88 = 94.63%
    rate_accum = calculate_implied_shipment_rate(
        weekly_output=71.88,
        current_inv=191.13,
        prev_inv=187.27,
    )
    assert rate_accum == 94.63

    # 3. 边界场景
    assert calculate_implied_shipment_rate(None, 100.0, 100.0) is None
    assert calculate_implied_shipment_rate(0.0, 100.0, 100.0) is None
    assert calculate_implied_shipment_rate(70.0, None, 100.0) is None


def test_soda_ash_mvp_pipeline_execution():
    """测试纯碱 MVP 全景对账管线执行与产物完整性。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline = SodaAshMvpPipeline(out_dir=tmp_dir)
        df, csv_p, md_p = pipeline.run()

        assert not df.is_empty()
        assert "report_month" in df.columns
        assert "soda_output_w_tons" in df.columns
        assert "cap_increment_w_tons" in df.columns
        assert "cum_cap_expansion_w_tons" in df.columns
        assert "survey_shipment_rate_pct" in df.columns
        assert "inventory_flow_regime" in df.columns

        assert csv_p.exists()
        assert md_p.exists()

        md_text = md_p.read_text(encoding="utf-8")
        assert "纯碱 (Soda Ash / SA) 全景基本面对账研报" in md_text
        assert "远兴能源" in md_text
        assert "库存双轨与产销状态" in md_text
        assert "中游蓄水池状态机诊断" in md_text
        assert "周期股分阶段量化交易门禁诊断" in md_text
        assert "左侧赔率建仓门禁" in md_text
        assert "右侧胜率确认门禁" in md_text
