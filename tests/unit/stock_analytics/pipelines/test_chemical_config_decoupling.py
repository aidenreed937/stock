"""化工品各子品种配置文件解耦与高内聚加载测试。"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from stock_analytics.pipelines.soda_ash.gates import (
    evaluate_trading_gates as evaluate_soda_ash_gates,
)
from stock_analytics.pipelines.soda_ash.gates import (
    load_trading_gates as load_soda_ash_gates,
)
from stock_analytics.pipelines.tio2.config import RegimeThresholds
from stock_analytics.pipelines.tio2.gates import (
    evaluate_trading_gates as evaluate_tio2_gates,
)
from stock_analytics.pipelines.tio2.gates import (
    load_trading_gates as load_tio2_gates,
)
from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator


def test_soda_ash_isolated_configs(tmp_path: Path) -> None:
    """验证纯碱模块高内聚配置的独立加载与门禁评估。"""
    cost_file = Path("config/industry/chemicals/soda_ash/cost_models.yaml")
    gates_file = Path("config/industry/chemicals/soda_ash/trading_gates.yaml")
    assert cost_file.exists(), "soda_ash/cost_models.yaml 必须存在"
    assert gates_file.exists(), "soda_ash/trading_gates.yaml 必须存在"

    cost_cfg = yaml.safe_load(cost_file.read_text(encoding="utf-8"))
    assert cost_cfg["symbol"] == "SA"
    assert "hou_process" in cost_cfg["models"]
    assert "solvay_process" in cost_cfg["models"]
    assert "natural_alkali" in cost_cfg["models"]
    assert cost_cfg["regime_thresholds"]["high_profit"] == 300.0

    gates_cfg = load_soda_ash_gates(gates_file)
    assert "left_side_odds" in gates_cfg
    assert "right_side_confirmation" in gates_cfg
    assert "top_escape" in gates_cfg
    assert "target_universe_mapping" in gates_cfg
    assert "alpha_leader" in gates_cfg["target_universe_mapping"]

    # 验证独立配置可驱动 evaluate_trading_gates
    df = pl.DataFrame(
        {
            "trade_date": ["2026-09-01"],
            "margin_regime": ["deep_loss"],
            "survey_operating_rate_pct": [72.0],
            "inventory_flow_regime": ["active_destocking"],
            "delta_factory_inv_w_tons": [-2.0],
        }
    )
    res = evaluate_soda_ash_gates(df, None, None, gates_cfg)
    assert "left_side_odds" in res
    assert "right_side_confirmation" in res
    assert "top_escape" in res


def test_tio2_isolated_configs() -> None:
    """验证钛白粉模块高内聚配置的独立加载与门禁评估。"""
    cost_file = Path("config/industry/chemicals/tio2/cost_models.yaml")
    gates_file = Path("config/industry/chemicals/tio2/trading_gates.yaml")
    assert cost_file.exists(), "tio2/cost_models.yaml 必须存在"
    assert gates_file.exists(), "tio2/trading_gates.yaml 必须存在"

    cost_cfg = yaml.safe_load(cost_file.read_text(encoding="utf-8"))
    assert cost_cfg["symbol"] == "TiO2"
    assert "sulfate_process" in cost_cfg["models"]
    assert "chloride_process" in cost_cfg["models"]
    assert "company_models" not in cost_cfg, "cost_models.yaml 剥离微观模型保持物理模型纯粹性"

    # 验证微观企业单一信任源 (SSOT) company_projections.yaml 具备完整参数
    proj_file = Path("config/industry/chemicals/tio2/company_projections.yaml")
    assert proj_file.exists(), "tio2/company_projections.yaml 必须存在"
    proj_cfg = yaml.safe_load(proj_file.read_text(encoding="utf-8"))
    assert "companies" in proj_cfg
    assert "002601.SZ" in proj_cfg["companies"]
    assert "002145.SZ" in proj_cfg["companies"]
    lb_sulfate = proj_cfg["companies"]["002601.SZ"]["segments"]["sulfate_tio2"]
    assert lb_sulfate["ore_captive_ratio"] == 0.65
    assert lb_sulfate["ore_captive_cash_cost"] == 900.0
    assert lb_sulfate["sulfate_acid_coeff"] == 3.0

    gates_cfg = load_tio2_gates(gates_file)
    assert "left_side_odds" in gates_cfg
    assert "right_side_confirmation" in gates_cfg
    assert "top_escape" in gates_cfg
    assert "target_universe_mapping" in gates_cfg

    # 验证独立配置可驱动 evaluate_trading_gates
    df = pl.DataFrame(
        {
            "trade_date": ["2026-09-01"],
            "margin_regime": ["deep_loss"],
            "delta_spot_price_cny": [100.0],
            "inventory_flow_regime": ["genuine_terminal_destocking"],
            "export_qty_yoy": [20.0],
        }
    )
    res = evaluate_tio2_gates(df, None, gates_cfg)
    assert "left_side_odds" in res
    assert "right_side_confirmation" in res
    assert "top_escape" in res


def test_pta_and_methanol_isolated_configs() -> None:
    """验证 PTA 与甲醇独立配置解析。"""
    pta_cost = Path("config/industry/chemicals/pta/cost_models.yaml")
    pta_gates = Path("config/industry/chemicals/pta/trading_gates.yaml")
    pta_proj = Path("config/industry/chemicals/pta/company_projections.yaml")
    ma_cost = Path("config/industry/chemicals/methanol/cost_models.yaml")

    assert pta_cost.exists()
    assert pta_gates.exists()
    assert pta_proj.exists()
    assert ma_cost.exists()

    pta_cfg = yaml.safe_load(pta_cost.read_text(encoding="utf-8"))
    assert "standard" in pta_cfg["models"]
    assert pta_cfg["regime_thresholds"]["high_profit"] == 600.0

    # 验证 PTA 双雄分部预测配置
    proj_cfg = yaml.safe_load(pta_proj.read_text(encoding="utf-8"))
    assert "companies" in proj_cfg
    assert "600346.SH" in proj_cfg["companies"]
    assert "601233.SH" in proj_cfg["companies"]
    hl_segments = proj_cfg["companies"]["600346.SH"]["segments"]
    assert "refining_and_chemicals" in hl_segments
    assert "pta_product" in hl_segments
    tk_segments = proj_cfg["companies"]["601233.SH"]["segments"]
    assert "polyester_filament" in tk_segments
    assert "zpc_investment_income" in tk_segments

    ma_cfg = yaml.safe_load(ma_cost.read_text(encoding="utf-8"))
    assert "coal_to_methanol" in ma_cfg["models"]


def test_spread_calculator_with_isolated_cost_configs(tmp_path: Path) -> None:
    """验证价差计算器自适应识别单品种高内聚配置。"""
    # 1. 单纯传入纯碱配置
    soda_calc = ChemicalSpreadCalculator(
        raw_dir=tmp_path,
        config_path="config/industry/chemicals/soda_ash/cost_models.yaml",
    )
    margin = soda_calc.calculate_soda_ash_double_ton_margin(
        soda_price=1600.0,
        nh4cl_price=350.0,
        salt_price=250.0,
        nh3_price=2400.0,
        coal_price=700.0,
    )
    assert isinstance(margin, float)

    # 2. 单纯传入钛白粉配置
    tio2_calc = ChemicalSpreadCalculator(
        raw_dir=tmp_path,
        config_path="config/industry/chemicals/tio2/cost_models.yaml",
    )
    tio2_margin = tio2_calc.calculate_tio2_sulfate_margin(
        tio2_price=15000.0,
        ilmenite_price=2200.0,
        acid_price=350.0,
    )
    assert isinstance(tio2_margin, float)

    # 3. 单纯传入 PTA 配置
    pta_calc = ChemicalSpreadCalculator(
        raw_dir=tmp_path,
        config_path="config/industry/chemicals/pta/cost_models.yaml",
    )
    pta_spread = pta_calc.calculate_pta_processing_spread(
        pta_price=5000.0,
        px_price=6800.0,
    )
    assert isinstance(pta_spread, float)


def test_migrated_products_cost_models_facade_removed_with_fallback(tmp_path: Path) -> None:
    """验证门面文件已彻底移除，且计算器默认直接聚合加载各品种级独立配置文件。"""
    facade_file = Path("config/industry/chemicals/chemical_cost_models.yaml")
    # 单点维护：彻底解耦，根目录门面文件不复存在
    assert not facade_file.exists(), "已彻底解耦，不应再存在 chemical_cost_models.yaml 门面文件"

    product_files = {
        "soda_ash": Path("config/industry/chemicals/soda_ash/cost_models.yaml"),
        "pta": Path("config/industry/chemicals/pta/cost_models.yaml"),
        "tio2": Path("config/industry/chemicals/tio2/cost_models.yaml"),
        "methanol": Path("config/industry/chemicals/methanol/cost_models.yaml"),
    }
    for _product, product_file in product_files.items():
        assert product_file.exists(), f"{product_file} 必须存在"
        product_cfg = yaml.safe_load(product_file.read_text(encoding="utf-8"))
        assert product_cfg["models"], f"{product_file} 模型段为空"

    # 计算器默认聚合：无需门面，直接聚合加载品种级文件，与单品种路径计算结果完全一致
    default_calc = ChemicalSpreadCalculator(raw_dir=tmp_path)
    soda_calc = ChemicalSpreadCalculator(
        raw_dir=tmp_path, config_path=str(product_files["soda_ash"])
    )
    pta_calc = ChemicalSpreadCalculator(raw_dir=tmp_path, config_path=str(product_files["pta"]))
    tio2_calc = ChemicalSpreadCalculator(raw_dir=tmp_path, config_path=str(product_files["tio2"]))

    soda_kwargs = dict(
        soda_price=1600.0, nh4cl_price=350.0, salt_price=250.0, nh3_price=2400.0, coal_price=700.0
    )
    assert default_calc.calculate_soda_ash_double_ton_margin(
        **soda_kwargs
    ) == soda_calc.calculate_soda_ash_double_ton_margin(**soda_kwargs)
    assert default_calc.calculate_pta_processing_spread(
        pta_price=5000.0, px_price=6800.0
    ) == pta_calc.calculate_pta_processing_spread(pta_price=5000.0, px_price=6800.0)
    tio2_kwargs = dict(tio2_price=15000.0, ilmenite_price=2200.0, acid_price=350.0)
    assert default_calc.calculate_tio2_sulfate_margin(
        **tio2_kwargs
    ) == tio2_calc.calculate_tio2_sulfate_margin(**tio2_kwargs)
    assert default_calc.calculate_tio2_sulfate_cash_cost(
        ilmenite_price=2200.0, acid_price=350.0
    ) == tio2_calc.calculate_tio2_sulfate_cash_cost(ilmenite_price=2200.0, acid_price=350.0)
    assert default_calc.get_margin_regime(2500.0, product="tio2") == "high_profit"


def test_migrated_products_gates_self_contained() -> None:
    """验证全部 8 大核心品种级门禁文件自足，且包含完整三门禁与标的映射，旧门面彻底移除。"""
    facade_file = Path("config/industry/chemicals/cyclical_trading_gates.yaml")
    assert not facade_file.exists(), "已彻底解耦，不应再存在 cyclical_trading_gates.yaml 门面文件"

    cases = {
        "soda_ash": Path("config/industry/chemicals/soda_ash/trading_gates.yaml"),
        "pta": Path("config/industry/chemicals/pta/trading_gates.yaml"),
        "tio2": Path("config/industry/chemicals/tio2/trading_gates.yaml"),
        "meg": Path("config/industry/chemicals/meg/trading_gates.yaml"),
        "methanol": Path("config/industry/chemicals/methanol/trading_gates.yaml"),
        "pvc": Path("config/industry/chemicals/pvc/trading_gates.yaml"),
        "polyurethane": Path("config/industry/chemicals/polyurethane/trading_gates.yaml"),
        "refrigerant": Path("config/industry/chemicals/refrigerant/trading_gates.yaml"),
    }
    for product, path in cases.items():
        assert path.exists(), f"{product} 交易门禁文件必须存在: {path}"
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        for section in ("left_side_odds", "right_side_confirmation", "top_escape"):
            assert section in cfg, f"{product} 门禁缺少 {section}"
            assert "name" in cfg[section]
            assert "rules" in cfg[section]
        assert "target_universe_mapping" in cfg, f"{product} 门禁缺少标的映射"

    tio2_cfg = yaml.safe_load(cases["tio2"].read_text(encoding="utf-8"))
    demand = tio2_cfg["right_side_confirmation"]["rules"]["demand_validation"]
    assert demand["export_volume_yoy_min"] == RegimeThresholds().destocking_export_yoy


def test_all_six_products_infrastructure_complete() -> None:
    """验证全部 6 大品种的标准四要素文件 (cost_models, companies, capacity_projects, README) 均完备自足。"""
    all_products = ["soda_ash", "pta", "tio2", "meg", "methanol", "pvc"]
    required_files = [
        "cost_models.yaml",
        "companies.yaml",
        "capacity_projects.yaml",
        "trading_gates.yaml",
        "README.md",
    ]

    for prod in all_products:
        base_dir = Path("config/industry/chemicals") / prod
        assert base_dir.is_dir(), f"品种目录不存在: {base_dir}"
        for req in required_files:
            file_path = base_dir / req
            assert file_path.exists(), f"{prod} 缺少基础设施文件: {file_path}"
            if req.endswith(".yaml"):
                cfg = yaml.safe_load(file_path.read_text(encoding="utf-8"))
                assert isinstance(cfg, dict), f"{file_path} YAML 内容必须为字典"
            elif req.endswith(".md"):
                content = file_path.read_text(encoding="utf-8")
                assert len(content) > 100, f"{file_path} 内容过短"


def test_company_elasticities_facade_removed_and_decentralized() -> None:
    """验证 company_elasticities.yaml 单体门面文件已彻底废弃，且弹性参数由各子模块高内聚提供。"""
    from stock_analytics.marts.chemical_elasticity_mart import load_company_elasticity_config

    facade_file = Path("config/industry/chemicals/company_elasticities.yaml")
    assert not facade_file.exists(), "已彻底解耦，不应再存在 company_elasticities.yaml 单体文件"

    # 验证新子模块目录完备
    for sub in ("polyurethane", "refrigerant"):
        sub_dir = Path("config/industry/chemicals") / sub
        assert sub_dir.is_dir(), f"{sub} 目录必须存在"
        assert (sub_dir / "companies.yaml").exists(), f"{sub}/companies.yaml 必须存在"
        assert (sub_dir / "README.md").exists(), f"{sub}/README.md 必须存在"

    # 验证自动聚合加载
    vat, companies = load_company_elasticity_config()
    assert vat == 0.13
    assert len(companies) >= 25
    codes = {c["commodity_code"] for c in companies}
    assert {
        "SA",
        "TA",
        "POY",
        "TIO2",
        "MDI",
        "TDI",
        "MA",
        "UR",
        "R32",
        "R134A",
        "MEG",
        "V",
    }.issubset(codes)
