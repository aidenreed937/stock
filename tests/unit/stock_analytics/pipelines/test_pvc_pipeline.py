"""聚氯乙烯 (PVC / V) 垂直量化深度爆破管线单元测试。"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.pvc.config import PVCConfig, load_pvc_config
from stock_analytics.pipelines.pvc.gates import evaluate_pvc_trading_gates
from stock_analytics.pipelines.pvc.panorama import (
    build_pvc_monthly_panorama,
    classify_pvc_inventory_regime,
    detect_pvc_regime_episodes,
)
from stock_analytics.pipelines.pvc.pipeline import PVCPipeline
from stock_analytics.pipelines.pvc.sources import (
    PVCCapacityProject,
    load_pvc_capacity_projects,
    load_pvc_cost_models,
)


def test_load_pvc_config_from_yaml() -> None:
    config = load_pvc_config("config/analytics/pvc.yaml")
    assert isinstance(config, PVCConfig)
    assert config.schema_version == 1
    assert config.artifact_root == "data/analytics/pvc"
    assert config.inputs.capacity_projects == "config/industry/chemicals/pvc/capacity_projects.yaml"
    assert config.inputs.trading_gates == "config/industry/chemicals/pvc/trading_gates.yaml"
    assert config.inputs.cost_models == "config/industry/chemicals/pvc/cost_models.yaml"
    assert config.regime.operating_rate_max == 75.0
    assert config.history.min_episode_months == 2


def test_load_pvc_capacity_and_cost() -> None:
    projects = load_pvc_capacity_projects("config/industry/chemicals/pvc/capacity_projects.yaml")
    assert len(projects) >= 4
    p0 = projects[0]
    assert isinstance(p0, PVCCapacityProject)
    assert p0.capacity_w_tons > 0

    costs = load_pvc_cost_models("config/industry/chemicals/pvc/cost_models.yaml")
    models = costs.get("models", {})
    assert "calcium_carbide_process" in models
    assert models["calcium_carbide_process"]["cash_cost_approx"] == 5100.0


def test_classify_pvc_inventory_regime() -> None:
    # 1. 天量仓单悬顶 (分位数 > 90% 且 Contango 贴水)
    r1 = classify_pvc_inventory_regime(
        basis_rate_pct=-1.5,
        warehouse_w_tons=30.0,
        warrant_pct_3y=95.0,
        delta_warrant=1.0,
        operating_rate_pct=80.0,
    )
    assert r1 == "bearish_contango_overhang"

    # 2. 真实终端去库 (开工正常 78% 且基差升水、仓单去化)
    r2 = classify_pvc_inventory_regime(
        basis_rate_pct=0.5,
        warehouse_w_tons=10.0,
        warrant_pct_3y=30.0,
        delta_warrant=-2.0,
        operating_rate_pct=78.0,
    )
    assert r2 == "genuine_terminal_destocking"


def test_evaluate_pvc_trading_gates() -> None:
    # 模拟现金成本击穿与低 PB -> 左侧建仓通过
    summary = evaluate_pvc_trading_gates(
        spot_price_cny=4710.0,
        cash_cost_cny=5100.0,
        operating_rate_pct=78.0,
        destocking_weeks=1,
        basis_rate_pct=-1.6,
        warehouse_w_tons=31.45,
        export_vol_yoy_pct=10.0,
        min_pb_10y_pct=10.0,
        min_pb_abs=0.57,
        config_path="config/industry/chemicals/pvc/trading_gates.yaml",
        as_of_date_str="2026-09-17",
    )
    assert summary.left_side.is_triggered is True
    assert summary.right_side.is_triggered is False
    assert summary.top_escape.is_triggered is False
    assert summary.current_stance == "OVERWEIGHT_LEFT"


def test_pvc_panorama_and_episodes() -> None:
    customs_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)],
            "export_volume_w_tons": [30.0, 32.0, 35.0],
            "export_value_w_usd": [2000.0, 2100.0, 2300.0],
            "export_volume_yoy_pct": [12.0, 15.0, 18.0],
        }
    )
    receipt_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 28), date(2026, 2, 28), date(2026, 3, 28)],
            "warrant_w_tons": [25.0, 26.0, 24.0],
            "warrant_contracts": [50000, 52000, 48000],
            "warrant_change": [100, 200, -400],
        }
    )
    basis_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 28), date(2026, 2, 28), date(2026, 3, 28)],
            "spot_price_cny": [4600.0, 4700.0, 4800.0],
            "futures_close_cny": [4700.0, 4750.0, 4820.0],
            "basis_cny": [-100.0, -50.0, -20.0],
            "basis_rate_pct": [-2.1, -1.0, -0.4],
            "basis_term_structure": ["CONTANGO", "CONTANGO", "CONTANGO"],
            "receipts_pctl_3y": [85.0, 88.0, 82.0],
        }
    )

    panorama = build_pvc_monthly_panorama(
        customs_df=customs_df,
        receipt_df=receipt_df,
        basis_df=basis_df,
    )
    assert not panorama.is_empty()
    assert "carbide_cash_margin_cny" in panorama.columns
    assert len(panorama) == 3

    episodes = detect_pvc_regime_episodes(panorama)
    assert isinstance(episodes, list)


def test_pvc_pipeline_end_to_end() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline = PVCPipeline()
        result = pipeline.run(
            as_of=date(2026, 9, 17),
            output_dir=tmp_dir,
            run_class="experiment",
            update_latest=False,
        )
        assert result.as_of_date == date(2026, 9, 17)
        assert not result.panorama.is_empty()
        assert not result.company_panel.is_empty()
        assert "聚氯乙烯" in result.report_markdown
        assert (
            Path(tmp_dir)
            / "runs"
            / f"as_of={result.as_of_date}"
            / result.paths.run_dir.name
            / "manifest.json"
        ).exists()
        assert (
            Path(tmp_dir)
            / "runs"
            / f"as_of={result.as_of_date}"
            / result.paths.run_dir.name
            / "pvc_report.md"
        ).exists()
