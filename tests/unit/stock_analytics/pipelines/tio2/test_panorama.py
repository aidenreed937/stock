"""钛白粉全景对账合并与状态机测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.tio2.config import HistoryConfig, RegimeThresholds
from stock_analytics.pipelines.tio2.panorama import (
    aggregate_capacity_by_month,
    classify_flow_regime,
    detect_regime_episodes,
    merge_monthly_panorama,
)


def test_aggregate_capacity_by_month() -> None:
    projects = [
        {"capacity_w_tons": 20.0, "actual_start": "2023-03-15"},
        {"capacity_w_tons": 10.0, "expected_start": "2023-03-20"},
        {"capacity_w_tons": 15.0, "expected_start": "2023-08-01"},
    ]
    incs = aggregate_capacity_by_month(projects)
    assert incs["2023-03"] == 30.0
    assert incs["2023-08"] == 15.0


def test_classify_flow_regime() -> None:
    t = RegimeThresholds()
    # 终端真去库 (海关出口高增 >= 15%)
    assert (
        classify_flow_regime(export_yoy=20.0, delta_spot_price=100.0, op_r=85.0, t=t)
        == "genuine_terminal_destocking"
    )
    # 被动累库 (出口收缩 < -5% 且价格下跌)
    assert (
        classify_flow_regime(export_yoy=-10.0, delta_spot_price=-200.0, op_r=85.0, t=t)
        == "passive_accumulation"
    )
    # 装置低开工主动去库
    assert (
        classify_flow_regime(export_yoy=5.0, delta_spot_price=0.0, op_r=70.0, t=t)
        == "active_destocking"
    )


def test_merge_monthly_panorama() -> None:
    customs_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "export_qty_tons": [130000.0, 140000.0],
            "export_value_usd": [2.8e8, 3.0e8],
            "export_qty_yoy": [12.0, 16.0],
            "export_unit_price_usd": [2153.8, 2142.9],
        }
    )
    spot_df = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "tio2_spot_price_cny": [15000.0, 15300.0],
            "tio2_spot_price_month_end": [15100.0, 15350.0],
        }
    )
    cap_inc = {"2026-07": 10.0}

    panorama = merge_monthly_panorama(
        customs_df=customs_df,
        spot_df=spot_df,
        cap_increment=cap_inc,
    )

    assert len(panorama) == 2
    assert "delta_spot_price_cny" in panorama.columns
    assert "inventory_flow_regime" in panorama.columns
    assert "cum_cap_expansion_w_tons" in panorama.columns

    rows = panorama.to_dicts()
    assert rows[0]["cap_increment_w_tons"] == 10.0
    assert rows[1]["cum_cap_expansion_w_tons"] == 10.0
    assert rows[1]["inventory_flow_regime"] == "genuine_terminal_destocking"


def test_merge_monthly_panorama_margin_fallback_config_driven() -> None:
    """价差缺失时按配置驱动的综合成本线推导毛利档位，不再硬编码 14000/16500/13500。"""
    spot_df = pl.DataFrame({"report_month": ["2026-08"], "tio2_spot_price_cny": [14000.0]})
    fallback = {
        "cost_line_cny": 12410.0,
        "high_profit": 2000.0,
        "profitable": 500.0,
        "near_breakeven": -500.0,
    }

    p = merge_monthly_panorama(customs_df=pl.DataFrame(), spot_df=spot_df, margin_fallback=fallback)
    row = p.to_dicts()[0]
    assert row["tio2_margin_cny"] == 1590.0
    assert row["margin_regime"] == "profitable"

    # 未提供 margin_fallback 时不估算，保持未知
    p2 = merge_monthly_panorama(customs_df=pl.DataFrame(), spot_df=spot_df)
    row2 = p2.to_dicts()[0]
    assert row2["tio2_margin_cny"] is None
    assert row2["margin_regime"] is None


def test_merge_monthly_panorama_wires_survey_and_ma20() -> None:
    """周度调研与 MA20 信号按月并入全景表。"""
    customs_df = pl.DataFrame({"report_month": ["2026-08"], "export_qty_tons": [100.0]})
    spot_df = pl.DataFrame({"report_month": ["2026-08"], "tio2_spot_price_cny": [15000.0]})
    weekly = pl.DataFrame(
        {
            "report_month": ["2026-08"],
            "operating_rate_pct": [75.0],
            "consecutive_destock_weeks": [3],
        }
    )
    ma20 = pl.DataFrame({"report_month": ["2026-08"], "ma20_break": [True]})

    p = merge_monthly_panorama(
        customs_df=customs_df,
        spot_df=spot_df,
        weekly_survey_df=weekly,
        ma20_df=ma20,
    )
    row = p.to_dicts()[0]
    assert row["operating_rate_pct"] == 75.0
    assert row["consecutive_destock_weeks"] == 3
    assert row["ma20_break"] is True


def test_detect_regime_episodes() -> None:
    panorama = pl.DataFrame(
        {
            "report_month": ["2021-06", "2021-07", "2021-08", "2022-01"],
            "tio2_spot_price_cny": [20500.0, 21000.0, 20800.0, 17000.0],
            "tio2_margin_cny": [2200.0, 2500.0, 2300.0, 800.0],
            "margin_regime": ["high_profit", "high_profit", "high_profit", "profitable"],
        }
    )
    cfg = HistoryConfig(min_episode_months=2, high_profit_margin=2000.0)
    episodes = detect_regime_episodes(panorama, cfg)
    assert len(episodes) == 1
    assert episodes[0]["kind"] == "high_profit"
    assert episodes[0]["duration_months"] == 3
    assert episodes[0]["start_month"] == "2021-06"
    assert episodes[0]["end_month"] == "2021-08"
