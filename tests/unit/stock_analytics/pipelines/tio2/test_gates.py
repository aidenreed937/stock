"""钛白粉周期股交易门禁评估测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.tio2.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)


def _latest_panorama() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-08"],
            "margin_regime": ["deep_loss"],
            "inventory_flow_regime": ["genuine_terminal_destocking"],
            "export_qty_yoy": [18.0],
            "delta_spot_price_cny": [200.0],
        }
    )


def _company_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": ["2026-08-28"],
            "symbol": ["002601.SZ"],
            "company_name": ["龙佰集团"],
            "pb_percentile_10y": [12.0],
            "pb": [1.4],
            "pe_ttm": [15.0],
        }
    )


def test_load_trading_gates_from_repo_config() -> None:
    cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    assert "left_side_odds" in cfg
    assert "right_side_confirmation" in cfg
    assert "top_escape" in cfg


def test_evaluate_trading_gates_left_side_unconfirmed_without_listing_data() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    result = evaluate_trading_gates(_latest_panorama(), _company_panel(), gates_cfg)
    # 挂牌价止跌/边际装置停产数据未接入 → 显式未确认，不触发左侧（杜绝“深跌+低PB”假裁决）
    assert result["left_side_odds"]["triggered"] is False
    assert "未接入" in result["left_side_odds"]["cond_listing_desc"]
    assert result["left_side_odds"]["cond_pb"] is True
    assert "leader_listing_price_stable_months" in result["left_side_odds"]["data_gaps"]


def test_evaluate_trading_gates_right_side_requires_ma_confirmation() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    result = evaluate_trading_gates(_latest_panorama(), _company_panel(), gates_cfg)
    # 现货提价 + 出口高增去库满足，但 MA20/开工率/协同检修等未接入数据源 → 右侧不触发
    assert result["right_side_confirmation"]["triggered"] is False
    assert result["right_side_confirmation"]["cond_hike"] is True
    assert result["right_side_confirmation"]["cond_destock"] is True
    assert "未接入" in result["right_side_confirmation"]["cond_ma_desc"]
    assert result["right_side_confirmation"]["data_gaps"]


def test_evaluate_trading_gates_top_escape_triggered() -> None:
    panorama = pl.DataFrame(
        {
            "report_month": ["2021-08"],
            "margin_regime": ["high_profit"],
            "inventory_flow_regime": ["passive_accumulation"],
            "export_qty_yoy": [-12.0],
            "delta_spot_price_cny": [-500.0],
        }
    )
    comp_panel = pl.DataFrame(
        {
            "trade_date": ["2021-08-31"],
            "symbol": ["002601.SZ"],
            "company_name": ["龙佰集团"],
            "pb_percentile_10y": [92.0],
            "pb": [3.8],
            "pe_ttm": [9.5],  # 低个位数见顶陷阱
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    result = evaluate_trading_gates(panorama, comp_panel, gates_cfg)
    assert result["top_escape"]["triggered"] is True
    assert result["top_escape"]["match_count"] >= 2
    assert "operating_rate_min" in result["top_escape"]["data_gaps"]
    assert result["top_escape"]["position_action"] == "clear_position"


def test_evaluate_trading_gates_top_escape_halve_at_two_signals() -> None:
    """框架口径：满足 2 项时减半离场，而非一票否决清仓。"""
    panorama = pl.DataFrame(
        {
            "report_month": ["2021-08"],
            "margin_regime": ["high_profit"],
            "inventory_flow_regime": ["passive_accumulation"],
            "export_qty_yoy": [-12.0],
            "delta_spot_price_cny": [-500.0],
        }
    )
    comp_panel = pl.DataFrame(
        {
            "trade_date": ["2021-08-31"],
            "symbol": ["002601.SZ"],
            "company_name": ["龙佰集团"],
            "pb_percentile_10y": [92.0],
            "pb": [3.8],
            "pe_ttm": [30.0],  # 不在低 PE 陷阱区间，使 match_count = 2
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    result = evaluate_trading_gates(panorama, comp_panel, gates_cfg)
    top = result["top_escape"]
    assert top["match_count"] == 2
    assert top["triggered"] is True
    assert top["position_action"] == "halve_position"


def test_evaluate_trading_gates_right_side_wired_conditions() -> None:
    """周度开工率/厂库去库/MA20 已接入时真实参与判定；协同检修缺失仍阻断触发。"""
    panorama = pl.DataFrame(
        {
            "report_month": ["2026-08"],
            "margin_regime": ["profitable"],
            "inventory_flow_regime": ["genuine_terminal_destocking"],
            "export_qty_yoy": [20.0],
            "delta_spot_price_cny": [200.0],
            "operating_rate_pct": [75.0],
            "consecutive_destock_weeks": [3],
            "ma20_break": [True],
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    right = evaluate_trading_gates(panorama, _company_panel(), gates_cfg)["right_side_confirmation"]
    assert right["cond_hike"] is True
    assert right["cond_destock"] is True
    assert right["cond_operating_rate"] is True
    assert right["cond_ma"] is True
    # 协同检修/挂牌价提价数据未接入 → 仍不能确认右侧触发
    assert right["triggered"] is False
    assert "oligopoly_coordinated_maintenance" in right["data_gaps"]
    assert "operating_rate_max" not in right["data_gaps"]


def test_evaluate_trading_gates_top_escape_counts_wired_operating_rate() -> None:
    """开工率接入后计入逃顶 match_count：高毛利 + 负荷打满 → 2 项 → 减半。"""
    panorama = pl.DataFrame(
        {
            "report_month": ["2021-08"],
            "margin_regime": ["high_profit"],
            "inventory_flow_regime": ["active_restocking"],
            "export_qty_yoy": [10.0],
            "delta_spot_price_cny": [300.0],
            "operating_rate_pct": [95.0],
        }
    )
    comp_panel = pl.DataFrame(
        {
            "trade_date": ["2021-08-31"],
            "symbol": ["002601.SZ"],
            "company_name": ["龙佰集团"],
            "pb_percentile_10y": [92.0],
            "pb": [3.8],
            "pe_ttm": [30.0],
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    top = evaluate_trading_gates(panorama, comp_panel, gates_cfg)["top_escape"]
    assert top["cond_operating_rate"] is True
    assert top["match_count"] == 2  # high_profit + operating_rate
    assert top["position_action"] == "halve_position"
    assert top["data_gaps"] == []


def test_evaluate_trading_gates_left_cond_loss_from_marginal_producer() -> None:
    """边际产能亏损改用公司口径：钛能 current_spot 硫酸法单吨毛利为负 → cond_loss=True 并输出数值说明。"""
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    result = evaluate_trading_gates(
        _latest_panorama(),
        _company_panel(),
        gates_cfg,
        marginal_margin_cny=-1947.0,
        marginal_margin_desc="边际产能(钛能化学)硫酸法单吨毛利: -1947 元/吨 (售价 14097 / 完全成本 16044)",
    )
    left = result["left_side_odds"]
    assert left["cond_loss"] is True
    assert "钛能化学" in left["cond_loss_desc"]
    assert left["marginal_margin_cny"] == -1947.0
    # 触发链仍要求挂牌价止跌/边际装置停产确认，不因诊断亏损而误触发
    assert left["triggered"] is False


def test_evaluate_trading_gates_empty_inputs() -> None:
    assert evaluate_trading_gates(pl.DataFrame(), None, {}) == {}


def test_evaluate_trading_gates_right_side_monthly_proxy_decidable() -> None:
    """周度调研缺失时，月频产能利用率/厂库代理使右侧门禁条件可判定（非“未接入”）。"""
    panorama = pl.DataFrame(
        {
            "report_month": ["2026-08", "2026-09"],
            "margin_regime": ["profitable", "profitable"],
            "inventory_flow_regime": ["neutral", "neutral"],
            "export_qty_yoy": [None, None],
            "delta_spot_price_cny": [-100.0, -542.7],
            "operating_rate_pct": [None, None],
            "consecutive_destock_weeks": [None, None],
            "operating_rate_pct_monthly": [73.3, None],
            "factory_inventory_w_tons_monthly": [None, None],
            "consecutive_destock_months": [0, None],
            "monthly_survey_as_of": ["2026-08", None],
            "ma20_break": [None, None],
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/tio2/trading_gates.yaml")
    right = evaluate_trading_gates(panorama, _company_panel(), gates_cfg)["right_side_confirmation"]
    # 开工率 73.3%（月度 2026-08）< 80% → 明确满足，不再“数据未接入”
    assert right["cond_operating_rate"] is True
    assert "月度调研(2026-08)" in right["cond_operating_rate_desc"]
    # 厂库无连续去库（0 个月）→ 明确不满足，且已用月频代理判定
    assert right["cond_destock"] is False
    assert "月频代理" in right["cond_destock_desc"]
    assert "operating_rate_max" not in right["data_gaps"]
    assert "destocking_weeks_min" not in right["data_gaps"]

    top = evaluate_trading_gates(panorama, _company_panel(), gates_cfg)["top_escape"]
    assert top["cond_operating_rate"] is False
    assert "月度调研(2026-08)" in top["cond_operating_rate_desc"]
    assert "operating_rate_min" not in top["data_gaps"]
