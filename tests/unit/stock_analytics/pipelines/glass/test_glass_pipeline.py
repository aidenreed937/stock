"""玻璃 (Glass / FG & PVG) 全景管线单元测试。"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.glass.config import RegimeThresholds, load_glass_config
from stock_analytics.pipelines.glass.gates import evaluate_glass_trading_gates
from stock_analytics.pipelines.glass.panorama import (
    aggregate_furnace_capacity_by_month,
    classify_glass_flow_regime,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.glass.pipeline import run_glass_pipeline


def test_glass_config_loading(tmp_path: Path) -> None:
    # 默认回退
    cfg = load_glass_config("non_existent_file.yaml")
    assert cfg.schema_version == 1
    assert "玻璃" in cfg.title
    assert cfg.regime.basis_speculative_cny == -30.0

    # 实际文件加载
    yaml_file = tmp_path / "glass.yaml"
    yaml_file.write_text(
        """
schema_version: 2
title: "测试玻璃管线"
regime:
  basis_speculative_cny: -50.0
""",
        encoding="utf-8",
    )
    loaded = load_glass_config(yaml_file)
    assert loaded.schema_version == 2
    assert loaded.title == "测试玻璃管线"
    assert loaded.regime.basis_speculative_cny == -50.0


def test_aggregate_furnace_capacity() -> None:
    furnaces = [
        {"capacity_t_d": 600.0, "actual_start": "2024-05-10"},
        {"capacity_t_d": 1000.0, "actual_start": "2024-05-20"},
        {"capacity_t_d": 800.0, "cold_repair_date": "2024-06-15"},
    ]
    deltas = aggregate_furnace_capacity_by_month(furnaces)
    assert deltas["2024-05"] == 1600.0
    assert deltas["2024-06"] == -800.0


def test_classify_glass_flow_regime() -> None:
    t = RegimeThresholds()
    # 真实刚需去库
    assert classify_glass_flow_regime(-5.0, 102.0, 80.0, t) == "genuine_terminal_destocking"
    # 深度冷修减产出清
    assert classify_glass_flow_regime(2.0, 96.0, 74.0, t) == "active_capacity_curtailment"
    # 需求钝化被动累库
    assert classify_glass_flow_regime(10.0, 92.0, 82.0, t) == "passive_inventory_accumulation"
    # 中性
    assert classify_glass_flow_regime(0.0, 96.0, 80.0, t) == "balanced_neutral"


def test_merge_monthly_panorama() -> None:
    glass_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "glass_output_w_cases": [7597.5, 7499.6],
            "glass_output_yoy": [-3.6, -7.6],
        }
    )
    soda_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "soda_output_w_tons": [341.7, 334.4],
            "soda_output_yoy": [11.3, 3.0],
        }
    )
    customs_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "export_qty_kg": [1000.0, 1100.0],
            "export_value_usd": [200.0, 220.0],
        }
    )
    weekly_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "survey_operating_rate_pct": [80.0, 78.5],
            "factory_inv_month_end_w_tons": [250.0, 280.0],
            "survey_shipment_rate_pct": [96.0, 94.0],
        }
    )
    empty_df = pl.DataFrame()

    panorama = merge_monthly_panorama(
        glass_df=glass_df,
        soda_df=soda_df,
        customs_df=customs_df,
        receipt_df=empty_df,
        futures_df=empty_df,
        weekly_survey_df=weekly_df,
    )

    assert len(panorama) == 2
    assert "scissors_spread_yoy" in panorama.columns
    # 2026-08: -7.6 - 3.0 = -10.6
    assert panorama.filter(pl.col("report_month") == "2026-08")["scissors_spread_yoy"][
        0
    ] == pytest.approx(-10.6)
    assert panorama["flow_regime"][1] == "passive_inventory_accumulation"


def test_evaluate_glass_trading_gates() -> None:
    panorama = pl.DataFrame(
        {
            "report_month": ["2026-08"],
            "glass_output_w_cases": [7499.6],
            "scissors_spread_yoy": [-10.6],
            "survey_operating_rate_pct": [78.6],
        }
    )
    company_panel = pl.DataFrame(
        {
            "symbol": ["601636.SH", "601865.SH"],
            "name": ["旗滨集团", "福莱特"],
            "pb": [1.08, 1.04],
            "pb_percentile_10y": [1.6, 1.3],
            "ma20_broken": [False, False],
            "role": ["float_alpha_leader", "pv_alpha_leader"],
        }
    )
    gates_cfg = {
        "left_side_odds": {"target_position_pct_max": 30.0},
        "right_side_confirmation": {"target_position_pct_max": 80.0},
    }

    eval_res = evaluate_glass_trading_gates(panorama, company_panel, {}, gates_cfg)
    # 左侧门禁应触发 (PB 分位 1.3% <= 15%)
    assert eval_res["left_side_odds"]["triggered"] is True
    # 右侧门禁未满足 (开工 > 75%, 剪刀差 < 0)
    assert eval_res["right_side_confirmation"]["triggered"] is False


def test_glass_pipeline_end_to_end(tmp_path: Path) -> None:
    res = run_glass_pipeline(output_dir=tmp_path / "glass_output")
    assert res.as_of_date is not None
    assert not res.panorama.is_empty()
    assert not res.company_panel.is_empty()
    assert "玻璃" in res.report_markdown
    assert (tmp_path / "glass_output" / "latest" / "manifest.json").exists()
    assert (tmp_path / "glass_output" / "latest" / "glass_panorama.parquet").exists()
