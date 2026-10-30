"""PTA 全景基本面对账管线单元测试。"""

from __future__ import annotations

import tempfile

import polars as pl

from stock_analytics.pipelines.pta.config import load_pta_config
from stock_analytics.pipelines.pta.gates import evaluate_trading_gates, load_trading_gates
from stock_analytics.pipelines.pta.panorama import (
    classify_chain_margin_regime,
    classify_flow_regime,
    classify_margin_regime,
)
from stock_analytics.pipelines.pta.pipeline import PtaPipeline
from stock_analytics.pipelines.pta.projections import (
    PtaCompanyProjectionEngine,
    build_financial_context,
)
from stock_data.core.runtime import DataRuntimeContext


def test_pta_config_load() -> None:
    """测试 PTA 顶层分析配置解析。"""
    cfg = load_pta_config("config/analytics/pta.yaml")
    assert cfg.schema_version == 1
    assert "PTA" in cfg.title
    assert cfg.artifact_root == "data/analytics/pta"
    assert "capacity_projects" in cfg.inputs.capacity_projects
    assert cfg.history.high_profit_margin == 600.0
    assert cfg.history.deep_loss_margin == 350.0


def test_pta_projections_engine_hengli_and_tongkun() -> None:
    """测试双雄 (恒力石化 vs 桐昆股份) SOTP 分部测算与情景推演。"""
    engine = PtaCompanyProjectionEngine("config/industry/chemicals/pta/company_projections.yaml")
    assert bool(engine.config)

    # 1. 恒力石化 600346.SH
    hl_ctx = build_financial_context("600346.SH")
    hl_scenarios = engine.project_all_scenarios("600346.SH", hl_ctx)
    assert len(hl_scenarios) == 3

    # 验证三情景利润单调性: trough < mid_cycle < peak
    hl_profits = {r.scenario_key: r.net_profit_cny for r in hl_scenarios}
    assert hl_profits["trough"] < hl_profits["mid_cycle"] < hl_profits["peak"]
    assert hl_profits["mid_cycle"] > 5.0e9  # 正常年化利润超过 50 亿

    # 验证底部 PB 资产重置底线 (解决周期底 PE 亏损导致市值归零的硬伤)
    trough_hl = next(r for r in hl_scenarios if r.scenario_key == "trough")
    assert trough_hl.valuation_method == "pb_asset_floor"
    assert trough_hl.target_pe is None
    assert trough_hl.target_pb == 1.05
    assert trough_hl.fair_market_value_cny > 6.0e10  # 资产托底约 701 亿元，绝非 0 元

    # 2. 桐昆股份 601233.SH
    tk_ctx = build_financial_context("601233.SH")
    tk_scenarios = engine.project_all_scenarios("601233.SH", tk_ctx)
    assert len(tk_scenarios) == 3
    tk_profits = {r.scenario_key: r.net_profit_cny for r in tk_scenarios}
    assert tk_profits["trough"] < tk_profits["mid_cycle"] < tk_profits["peak"]

    trough_tk = next(r for r in tk_scenarios if r.scenario_key == "trough")
    assert trough_tk.valuation_method == "pb_asset_floor"
    assert trough_tk.target_pb == 0.85
    assert trough_tk.fair_market_value_cny > 3.0e10  # 资产托底约 325 亿元，绝非 0 元

    # 验证浙石化投资收益计入
    mid_res = next(r for r in tk_scenarios if r.scenario_key == "mid_cycle")
    assert mid_res.equity_investment_income_cny > 0

    # 3. 敏感性矩阵测试
    sens_df = engine.generate_sensitivity_matrix(
        symbol="600346.SH",
        x_name="pta_price",
        x_values=[5000.0, 5500.0, 6000.0],
        y_name="px_price",
        y_values=[7000.0, 7500.0],
        context=hl_ctx,
    )
    assert not sens_df.is_empty()
    assert "px_price_cny" in sens_df.columns
    assert "5000" in sens_df.columns
    assert "6000" in sens_df.columns


def test_pta_gates_evaluation() -> None:
    """测试 PTA A 类大宗标准化门禁规则裁决。"""
    gates_cfg = load_trading_gates("config/industry/chemicals/pta/trading_gates.yaml")

    # 构造假数据: 加工费跌破 350 元/吨
    df_loss = pl.DataFrame(
        {
            "report_month": ["2026-09"],
            "margin_regime": ["deep_loss"],
            "inventory_flow_regime": ["passive_accumulation"],
            "basis_rate_pct": [-2.5],
            "scissors_spread_yoy": [-5.0],
            "polyester_export_yoy": [2.0],
        }
    )
    res_loss = evaluate_trading_gates(df_loss, None, gates_cfg)
    assert res_loss["gate_details"]["left_side_odds"]["triggered"] is True

    # 构造假数据: 暴利逃顶 (加工费超额暴利 + 被动累库)
    df_top = pl.DataFrame(
        {
            "report_month": ["2026-09"],
            "margin_regime": ["high_profit"],
            "inventory_flow_regime": ["passive_accumulation"],
            "basis_rate_pct": [1.5],
            "scissors_spread_yoy": [-3.0],
            "polyester_export_yoy": [-1.0],
        }
    )
    res_top = evaluate_trading_gates(df_top, None, gates_cfg)
    assert res_top["overall_regime"] == "top_escape"
    assert res_top["recommended_action"] == "clear_position"


def test_pta_panorama_helpers() -> None:
    """测试全景表辅助算子。"""
    assert classify_margin_regime(650.0) == "high_profit"
    assert classify_margin_regime(500.0) == "profitable"
    assert classify_margin_regime(400.0) == "near_breakeven"
    assert classify_margin_regime(300.0) == "deep_loss"

    assert (
        classify_flow_regime(scissors=5.0, delta_receipt=-100.0, spread=450.0)
        == "genuine_terminal_destocking"
    )
    assert (
        classify_flow_regime(scissors=-5.0, delta_receipt=100.0, spread=450.0)
        == "passive_accumulation"
    )

    # 上下游双加工差状态机测试
    assert classify_chain_margin_regime(pta_spread=600.0, poy_spread=1400.0) == "both_profitable"
    assert (
        classify_chain_margin_regime(pta_spread=200.0, poy_spread=1300.0) == "downstream_expansion"
    )
    assert classify_chain_margin_regime(pta_spread=600.0, poy_spread=600.0) == "upstream_squeeze"
    assert classify_chain_margin_regime(pta_spread=200.0, poy_spread=600.0) == "both_loss"


def test_pta_pipeline_end_to_end() -> None:
    """端到端运行 PTA 管线并验证产物落盘与 Manifest。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        runtime = DataRuntimeContext.from_root("data")
        pipeline = PtaPipeline(runtime=runtime)

        result = pipeline.run(output_dir=tmp_dir, update_latest=False)

        assert result.as_of_date is not None
        assert not result.panorama.is_empty()
        assert "report_month" in result.panorama.columns
        assert "pta_output_w_tons" in result.panorama.columns
        assert "synthetic_fiber_production" in result.panorama.columns
        assert "poy_spread_monthly_avg" in result.panorama.columns
        assert "chain_margin_regime" in result.panorama.columns

        # 验证双雄预测表物化
        assert result.company_projections is not None
        assert not result.company_projections.is_empty()
        symbols = result.company_projections.get_column("symbol").unique().to_list()
        assert "600346.SH" in symbols
        assert "601233.SH" in symbols

        # 验证产物文件物理落盘
        run_dir = result.paths.run_dir
        assert (run_dir / "panorama.csv").exists()
        assert (run_dir / "panorama.parquet").exists()
        assert (run_dir / "report.md").exists()
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "company_projections.csv").exists()

        manifest = result.manifest
        assert manifest["pipeline_name"] == "pta_pipeline"
        assert manifest["artifact_type"] == "pta_panorama"
        assert "outputs" in manifest
