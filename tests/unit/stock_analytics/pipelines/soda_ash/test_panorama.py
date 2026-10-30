"""纯碱全景合并/衍生/状态机/历史拐点检测测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.soda_ash.config import HistoryConfig, RegimeThresholds
from stock_analytics.pipelines.soda_ash.panorama import (
    aggregate_capacity_by_month,
    classify_flow_regime,
    detect_regime_episodes,
    latest_core_row,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.soda_ash.sources import calculate_implied_shipment_rate


def test_calculate_implied_shipment_rate() -> None:
    assert calculate_implied_shipment_rate(100.0, 110.0, 100.0) == 90.0
    assert calculate_implied_shipment_rate(100.0, 95.0, 100.0) == 105.0
    assert calculate_implied_shipment_rate(0.0, 10.0, 10.0) is None
    assert calculate_implied_shipment_rate(None, 10.0, 10.0) is None


def test_aggregate_capacity_by_month() -> None:
    projects = [
        {"actual_start": "2023-06", "capacity_w_tons": 150.0, "status": "operating"},
        {
            "expected_start": "2023-06",
            "actual_start": None,
            "capacity_w_tons": 50.0,
            "status": "under_construction",
        },
        {"actual_start": "2024-01", "capacity_w_tons": 100.0, "status": "operating"},
        {
            "expected_start": "2026-06",
            "actual_start": None,
            "capacity_w_tons": 280.0,
            "status": "under_construction",
        },
    ]
    # 在建项目的 expected_start 属计划而非事实，不得提前计入累计有效产能（防前视）
    assert aggregate_capacity_by_month(projects) == {"2023-06": 150.0, "2024-01": 100.0}


def test_latest_core_row_skips_pending_tail_month() -> None:
    df = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07", "2026-08"],
            "soda_output_w_tons": [336.4, 341.7, None],
            "warehouse_receipt_month_end": [8181.0, 4001.0, 5280.0],
        }
    )
    row = latest_core_row(df)
    assert row is not None
    assert row["report_month"] == "2026-07"
    assert row["warehouse_receipt_month_end"] == 4001.0


def test_latest_core_row_falls_back_when_all_core_null() -> None:
    df = pl.DataFrame({"report_month": ["2026-08"], "soda_output_w_tons": [None]})
    row = latest_core_row(df)
    assert row is not None
    assert row["report_month"] == "2026-08"
    assert latest_core_row(pl.DataFrame()) is None


def test_classify_flow_regime_all_branches() -> None:
    t = RegimeThresholds()
    assert classify_flow_regime(None, None, None, None, None, t) == "--"
    # 实务去库；深度升水 + 仓单累积 → 投机移库
    assert classify_flow_regime(-1.0, None, 300.0, -50.0, 80.0, t) == "speculative_transfer_risk"
    assert classify_flow_regime(-1.0, None, 10.0, -50.0, 80.0, t) == "genuine_terminal_destocking"
    # 被动累库：库存增加且出货率低
    assert classify_flow_regime(1.0, 95.0, 0.0, 0.0, 80.0, t) == "passive_accumulation"
    # 主动减产去库：开工率 < 75（无去库/累库信号时）
    assert classify_flow_regime(0.0, None, 0.0, 0.0, 70.0, t) == "active_destocking"
    # 紧平衡
    assert classify_flow_regime(0.0, 98.0, 0.0, 0.0, 80.0, t) == "balanced_neutral"
    # 纯库存累积
    assert classify_flow_regime(2.0, None, 0.0, 0.0, 80.0, t) == "passive_accumulation"
    assert classify_flow_regime(0.0, 80.0, 0.0, 0.0, 80.0, t) == "neutral"


def _soda_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "soda_output_w_tons": [200.0, 210.0, 220.0],
            "soda_output_yoy": [5.0, 6.0, 7.0],
        }
    )


def test_merge_monthly_panorama_derived_columns() -> None:
    glass = pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "glass_output_w_cases": [7000.0, 7100.0, 7200.0],
            "glass_output_yoy": [3.0, 4.0, 5.0],
        }
    )
    spreads = pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "soda_spot_price_cny": [1800.0, 1750.0, 1700.0],
            "double_ton_margin_cny": [100.0, 50.0, 0.0],
            "margin_regime": ["normal", "near_breakeven", "deep_loss"],
        }
    )
    futures = pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "futures_settle_month_end": [1700.0, 1700.0, 1700.0],
        }
    )
    factory = pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "factory_inv_month_end_w_tons": [100.0, 99.0, 120.0],
            "survey_shipment_rate_pct": [99.0, 101.0, 95.0],
            "survey_operating_rate_pct": [80.0, 80.0, 80.0],
        }
    )
    receipt = pl.DataFrame(
        {
            "report_month": ["2023-01", "2023-02", "2023-03"],
            "warehouse_receipt_month_end": [100.0, 110.0, 500.0],
        }
    )

    out = merge_monthly_panorama(
        soda_df=_soda_frame(),
        glass_df=glass,
        customs_df=pl.DataFrame(),
        cap_increment={"2023-01": 150.0},
        receipt_df=receipt,
        factory_df=factory,
        spreads_df=spreads,
        futures_df=futures,
        hold_rank_df=None,
    )
    assert len(out) == 3
    assert out["scissors_spread_yoy"].to_list() == [-2.0, -2.0, -2.0]
    assert out["basis_month_end"].to_list() == [100.0, 50.0, 0.0]
    assert out["cum_cap_expansion_w_tons"].to_list() == [150.0, 150.0, 150.0]
    assert out["delta_factory_inv_w_tons"].to_list() == [None, -1.0, 21.0]
    assert out["delta_warehouse_receipt"].to_list() == [None, 10.0, 390.0]
    # 2023-01 去库 + 基差 100 → 真实去库；2023-03 被动累库
    assert out["inventory_flow_regime"].to_list() == [
        "genuine_terminal_destocking",
        "genuine_terminal_destocking",
        "passive_accumulation",
    ]


def test_detect_regime_episodes_groups_consecutive_months() -> None:
    rows = []
    for month, margin, regime in (
        ("2021-07", 1200.0, "high_profit"),
        ("2021-08", 1300.0, "high_profit"),
        ("2021-09", 1400.0, "high_profit"),
        ("2021-10", 200.0, "normal"),
        ("2023-11", -300.0, "deep_loss"),
        ("2023-12", -400.0, "deep_loss"),
    ):
        rows.append(
            {
                "report_month": month,
                "double_ton_margin_cny": margin,
                "margin_regime": regime,
                "soda_spot_price_cny": 1800.0 if margin > 0 else 1300.0,
                "scissors_spread_yoy": 5.0,
            }
        )
    panorama = pl.DataFrame(rows)
    episodes = detect_regime_episodes(panorama, HistoryConfig(min_episode_months=2))
    assert len(episodes) == 2
    high = next(ep for ep in episodes if ep["kind"] == "high_profit")
    low = next(ep for ep in episodes if ep["kind"] == "deep_loss")
    assert (high["start"], high["end"]) == ("2021-07", "2021-09")
    assert high["margin_max"] == 1400.0
    assert (low["start"], low["end"]) == ("2023-11", "2023-12")
    assert low["transition_note"] is None


def test_detect_regime_episodes_uses_history_thresholds_over_label() -> None:
    """history 数值阈值优先：标签为 high_profit 但利润落在中性区间的月份必须切断状态期。"""
    rows = [
        {
            "report_month": "2021-07",
            "double_ton_margin_cny": 1200.0,
            "margin_regime": "high_profit",
        },
        {
            "report_month": "2021-08",
            "double_ton_margin_cny": 400.0,
            "margin_regime": "high_profit",
        },
        {
            "report_month": "2021-09",
            "double_ton_margin_cny": 1300.0,
            "margin_regime": "high_profit",
        },
    ]
    episodes = detect_regime_episodes(pl.DataFrame(rows), HistoryConfig(min_episode_months=1))
    assert len(episodes) == 2
    assert {(ep["start"], ep["end"]) for ep in episodes} == {
        ("2021-07", "2021-07"),
        ("2021-09", "2021-09"),
    }


def test_detect_regime_episodes_numeric_only_without_label() -> None:
    rows = [
        {"report_month": "2021-08", "double_ton_margin_cny": 900.0, "margin_regime": None},
        {"report_month": "2021-09", "double_ton_margin_cny": 1100.0, "margin_regime": None},
    ]
    episodes = detect_regime_episodes(pl.DataFrame(rows), HistoryConfig(min_episode_months=2))
    assert len(episodes) == 1
    assert episodes[0]["kind"] == "high_profit"
