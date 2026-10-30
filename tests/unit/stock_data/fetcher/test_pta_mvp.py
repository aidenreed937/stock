"""PTA (精对苯二甲酸 / TA) 最小可行闭环 (MVP) 单元测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from stock_analytics.marts.pta_company_panel import (
    build_pta_company_panel,
    load_pta_company_configs,
)
from stock_analytics.pipelines.pta.pipeline import PtaPipeline
from stock_data.catalog import DataCatalog
from stock_data.fetcher.industry.chemicals.collectors.spreads import (
    ChemicalSpreadCalculator,
)


def test_pta_capacity_projects_yaml_valid() -> None:
    """测试 PTA 重大产能事件种子库合法性。"""
    p_path = Path("config/industry/chemicals/pta/capacity_projects.yaml")
    assert p_path.exists(), "pta/capacity_projects.yaml 必须存在"
    data = yaml.safe_load(p_path.read_text(encoding="utf-8"))
    assert "projects" in data
    projects = data["projects"]
    assert len(projects) >= 6

    # 必须包含恒力石化大连/惠州与逸盛新材料
    hengli = [p for p in projects if "恒力石化" in p["company"]]
    assert len(hengli) >= 2
    total_hl_cap = sum(p["capacity_w_tons"] for p in hengli)
    assert total_hl_cap >= 1000.0

    # 必须包含老旧装置淘汰
    shutdowns = [p for p in projects if p.get("status") == "shutdown"]
    assert len(shutdowns) >= 1
    assert shutdowns[0]["capacity_w_tons"] < 0


def test_pta_companies_yaml_valid() -> None:
    """测试 PTA 核心上市公司画像配置合法性。"""
    cfg_path = Path("config/industry/chemicals/pta/companies.yaml")
    assert cfg_path.exists(), "pta/companies.yaml 必须存在"
    companies = load_pta_company_configs(cfg_path)
    assert len(companies) >= 5

    symbols = [c["symbol"] for c in companies]
    assert "600346.SH" in symbols  # 恒力石化
    assert "002493.SZ" in symbols  # 荣盛石化
    assert "601233.SH" in symbols  # 桐昆股份
    assert "603225.SH" in symbols  # 新凤鸣
    assert "000703.SZ" in symbols  # 恒逸石化


def test_pta_cost_model_and_regimes() -> None:
    """测试 PTA 理论加工费与盈亏状态机。"""
    calc = ChemicalSpreadCalculator(
        raw_dir="data/raw/industry/chemicals",
        config_path="config/industry/chemicals/pta/cost_models.yaml",
    )
    models = calc.load_cost_models()
    assert "pta" in models.get("models", {})
    assert "pta" in models.get("regime_thresholds", {})

    # PTA 加工费 = 6000 - 0.655 * 8000 = 6000 - 5240 = 760.0
    spread = calc.calculate_pta_processing_spread(pta_price=6000.0, px_price=8000.0)
    assert spread == 760.0

    # POY 加工差 = 7500 - 0.855 * 5500 - 0.335 * 4500 = 7500 - 4702.5 - 1507.5 = 1290.0
    poy_spread = calc.calculate_polyester_poy_spread(
        poy_price=7500.0, pta_price=5500.0, meg_price=4500.0
    )
    assert poy_spread == 1290.0


def test_pta_company_panel_build() -> None:
    """测试 PTA 上市公司面板构建与反向时钟判定。"""
    cat = DataCatalog("tushare")
    df = build_pta_company_panel(catalog=cat)
    assert not df.is_empty()
    assert "trade_date" in df.columns
    assert "symbol" in df.columns
    assert "pb_percentile_10y" in df.columns
    assert "valuation_regime" in df.columns

    # 验证覆盖 5 家标的
    unique_symbols = df.get_column("symbol").unique().to_list()
    assert len(unique_symbols) == 5
    assert "600346.SH" in unique_symbols


def test_pta_pipeline_execution() -> None:
    """测试 PTA 全景对账管线端到端执行与产物完整性。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline = PtaPipeline()
        result = pipeline.run(output_dir=tmp_dir, update_latest=False)
        df = result.panorama

        assert not df.is_empty()
        assert "report_month" in df.columns
        assert "pta_output_w_tons" in df.columns
        assert "synthetic_fiber_production" in df.columns
        assert "scissors_spread_yoy" in df.columns
        assert "warehouse_receipt_month_end" in df.columns
        assert "polyester_export_w_tons" in df.columns
        assert "polyester_export_yoy" in df.columns
        assert "export_pull_rate_pct" in df.columns
        assert "inventory_flow_regime" in df.columns

        run_dir = result.paths.run_dir
        assert (run_dir / "panorama.csv").exists()
        assert (run_dir / "report.md").exists()

        md_text = (run_dir / "report.md").read_text(encoding="utf-8")
        assert "PTA (精对苯二甲酸 / TA)" in md_text
        assert "恒力石化" in md_text
        assert "期货仓单与库存蓄水池" in md_text
        assert "GACC 海关出口与海外外需泄洪对账" in md_text
        assert "周期股分阶段量化交易门禁诊断" in md_text
        assert "commodity_standard_gate" in md_text
