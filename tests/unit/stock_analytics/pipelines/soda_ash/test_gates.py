"""纯碱周期股交易门禁评估测试。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.soda_ash.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)


def _destocking_rows() -> list[dict[str, Any]]:
    """构造连续 3 期去库的全景尾段（满足 destocking_weeks_min = 3）。"""
    return [
        {
            "report_month": "2026-02",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 76.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -3.0,
            "scissors_spread_yoy": 1.0,
            "export_qty_yoy": 20.0,
        },
        {
            "report_month": "2026-03",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 74.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -4.0,
            "scissors_spread_yoy": 1.5,
            "export_qty_yoy": 22.0,
        },
        {
            "report_month": "2026-04",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 70.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -5.0,
            "scissors_spread_yoy": 2.5,
            "export_qty_yoy": 25.0,
        },
    ]


def _latest_panorama() -> pl.DataFrame:
    return pl.DataFrame(_destocking_rows())


def _company_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": ["2026-04-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [2.0],  # 2.0 代表 2% 分位 (与 Mart 口径一致)
            "pb": [0.79],
            "pe_ttm": [15.0],
        }
    )


def test_load_trading_gates_from_repo_config() -> None:
    cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    assert "left_side_odds" in cfg
    assert "right_side_confirmation" in cfg
    assert "top_escape" in cfg
    # 验证新阈值 0.78
    assert cfg["right_side_confirmation"]["rules"]["operating_rate_max"] == 0.78
    # 验证季节性规则配置
    rules = cfg["right_side_confirmation"]["rules"]
    assert "seasonal_filters" in rules
    assert rules["seasonal_filters"]["blackout_months"] == [12, 1]
    # 逃顶为多因子投票制，票数阈值必须显式配置
    assert cfg["top_escape"]["rules"]["trigger_match_count_min"] == 3
    assert cfg["top_escape"]["rules"]["warning_match_count_min"] == 2


def test_evaluate_trading_gates_left_side_triggered() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    result = evaluate_trading_gates(
        _latest_panorama(), _company_panel(), {"basis_rate_pct": 1.0}, gates_cfg
    )
    assert result["as_of_month"] == "2026-04"
    assert result["left_side_odds"]["triggered"] is True
    assert "deep_loss" in result["left_side_odds"]["cond_margin_desc"]
    assert "中盐化工" in result["left_side_odds"]["cond_pb_desc"]
    assert "春季复工补库黄金窗口" in result["left_side_odds"]["cond_seasonal_desc"]
    # 门禁指定角色（alpha_leader 远兴能源）不在本标的面内 → 显式提示数据未接入
    assert "门禁指定角色" in result["left_side_odds"]["cond_role_pb_desc"]


def test_evaluate_trading_gates_right_side_pending_without_ma() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    result = evaluate_trading_gates(
        _latest_panorama(), _company_panel(), {"basis_rate_pct": 1.0}, gates_cfg
    )
    # 开工率/去库/基差/需求均满足，但单个样本点无 MA20 突破确认 → 右侧门禁不触发
    assert result["right_side_confirmation"]["triggered"] is False
    assert "MA20 突破: 未确认/待行情" in result["right_side_confirmation"]["cond_ma_desc"]


def test_evaluate_trading_gates_right_side_requires_consecutive_destocking() -> None:
    """连续去库期数不足 destocking_weeks_min 时右侧门禁必须被拦截。"""
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    panel = pl.DataFrame(
        {
            "trade_date": ["2026-01-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [12.0],
            "pb": [0.85],
            "pe_ttm": [15.0],
            "ma20_break": [True],
        }
    )
    # 仅 2 期连续去库（< 3）
    short = pl.DataFrame(_destocking_rows()[1:])
    result = evaluate_trading_gates(short, panel, {"basis_rate_pct": 1.5}, gates_cfg)
    assert result["right_side_confirmation"]["triggered"] is False
    assert "连续去库 2 期" in result["right_side_confirmation"]["cond_destock_desc"]
    assert "需 >= 3 期" in result["right_side_confirmation"]["cond_destock_desc"]


def test_evaluate_trading_gates_right_side_all_confirmed() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    # 构造显式带 ma20_break 的标的面
    panel = pl.DataFrame(
        {
            "trade_date": ["2026-01-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [12.0],  # 12% 分位 <= 40% 天花板
            "pb": [0.85],
            "pe_ttm": [15.0],
            "ma20_break": [True],
        }
    )
    result = evaluate_trading_gates(_latest_panorama(), panel, {"basis_rate_pct": 1.5}, gates_cfg)
    assert result["right_side_confirmation"]["triggered"] is True
    assert "已突破" in result["right_side_confirmation"]["cond_ma_desc"]
    assert "出口同比 +25.0%" in result["right_side_confirmation"]["cond_demand_desc"]


def test_evaluate_trading_gates_right_side_valuation_ceiling_blocked() -> None:
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    # 估值已高达 55% 分位，超过 40% 天花板
    panel = pl.DataFrame(
        {
            "trade_date": ["2026-01-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [55.0],
            "pb": [1.45],
            "pe_ttm": [15.0],
            "ma20_break": [True],
        }
    )
    result = evaluate_trading_gates(_latest_panorama(), panel, {"basis_rate_pct": 1.5}, gates_cfg)
    # 估值超标，拦截右侧加码追多
    assert result["right_side_confirmation"]["triggered"] is False


def test_evaluate_trading_gates_top_escape_triggered() -> None:
    panorama = pl.DataFrame(
        {
            "report_month": ["2021-09"],
            "margin_regime": ["high_profit"],
            "survey_operating_rate_pct": [92.0],
            "inventory_flow_regime": ["passive_accumulation"],
            "delta_factory_inv_w_tons": [10.0],
            "scissors_spread_yoy": [-5.0],
            "export_qty_yoy": [-10.0],
        }
    )
    # 带有低 PE 见顶陷阱 (PE = 6.2 < 8.0) 且 PB 处于 85% 高位
    panel = pl.DataFrame(
        {
            "trade_date": ["2021-09-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [85.0],
            "pb": [2.8],
            "pe_ttm": [6.2],
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    result = evaluate_trading_gates(panorama, panel, None, gates_cfg)
    top = result["top_escape"]
    assert top["triggered"] is True
    assert top["match_count"] >= 3
    assert top["trigger_match_count_min"] == 3
    assert "清仓门禁" in top["suggestion"]
    # 条件对账必须来自真实评估结果，而非渲染层硬编码
    assert "行业开工负荷打满: 是" in top["cond_op_desc"]
    assert "理论利润超额暴利: 是" in top["cond_margin_desc"]
    assert "中游逆势被动累库: 是" in top["cond_flow_desc"]
    assert "静态低 PE 见顶陷阱: 是" in top["cond_pe_desc"]
    assert "高估值 + 内外需背离: 是" in top["cond_divergence_desc"]


def test_evaluate_trading_gates_top_escape_conditions_reflect_false_state() -> None:
    """逃顶未触发时，各条件对账必须如实显示「否」，不得硬编码。"""
    panorama = pl.DataFrame(
        {
            "report_month": ["2026-07"],
            "margin_regime": ["profitable"],
            "survey_operating_rate_pct": [79.0],
            "inventory_flow_regime": ["balanced_neutral"],
            "delta_factory_inv_w_tons": [1.0],
            "scissors_spread_yoy": -14.9,
            "export_qty_yoy": None,
        }
    )
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    result = evaluate_trading_gates(panorama, None, None, gates_cfg)
    top = result["top_escape"]
    assert top["triggered"] is False
    assert "行业开工负荷打满: 否" in top["cond_op_desc"]
    assert "理论利润超额暴利: 否" in top["cond_margin_desc"]
    assert "中游逆势被动累库: 否" in top["cond_flow_desc"]


def test_evaluate_trading_gates_empty_inputs() -> None:
    assert evaluate_trading_gates(pl.DataFrame(), None, None, {}) == {}


def test_evaluate_trading_gates_right_side_seasonal_blackout() -> None:
    """验证处于 12 月或 1 月春节淡季黑洞期时，一票否决右侧买入门禁。"""
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    # 构造处于 2026-01 (1月) 且各项基本面已达标的场景
    jan_rows = [
        {
            "report_month": "2025-11",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 74.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -3.0,
            "scissors_spread_yoy": 1.0,
            "export_qty_yoy": 20.0,
        },
        {
            "report_month": "2025-12",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 72.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -4.0,
            "scissors_spread_yoy": 1.5,
            "export_qty_yoy": 22.0,
        },
        {
            "report_month": "2026-01",
            "margin_regime": "deep_loss",
            "survey_operating_rate_pct": 70.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -5.0,
            "scissors_spread_yoy": 2.5,
            "export_qty_yoy": 25.0,
        },
    ]
    panel = pl.DataFrame(
        {
            "trade_date": ["2026-01-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [12.0],
            "pb": [0.85],
            "pe_ttm": [15.0],
            "ma20_break": [True],
        }
    )
    result = evaluate_trading_gates(
        pl.DataFrame(jan_rows), panel, {"basis_rate_pct": 1.5}, gates_cfg
    )
    right = result["right_side_confirmation"]
    assert right["triggered"] is False
    assert "淡季被动累库黑洞期" in right["cond_seasonal_desc"]
    assert "一票否决" in right["cond_seasonal_desc"]
    assert "季节性规则拦截" in right["suggestion"]


def test_evaluate_trading_gates_right_side_turnaround_inspection() -> None:
    """验证处于 9 月秋检但未亏损时，开工下降被识别为例行检修，否决右侧确认。"""
    gates_cfg = load_trading_gates("config/industry/chemicals/soda_ash/trading_gates.yaml")
    sep_rows_profitable = [
        {
            "report_month": "2026-07",
            "margin_regime": "profitable",
            "survey_operating_rate_pct": 76.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -3.0,
            "scissors_spread_yoy": 1.0,
            "export_qty_yoy": 20.0,
        },
        {
            "report_month": "2026-08",
            "margin_regime": "profitable",
            "survey_operating_rate_pct": 74.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -4.0,
            "scissors_spread_yoy": 1.5,
            "export_qty_yoy": 22.0,
        },
        {
            "report_month": "2026-09",
            "margin_regime": "profitable",  # 秋检开工虽降，但毛利仍盈利
            "survey_operating_rate_pct": 70.0,
            "inventory_flow_regime": "genuine_terminal_destocking",
            "delta_factory_inv_w_tons": -5.0,
            "scissors_spread_yoy": 2.5,
            "export_qty_yoy": 25.0,
        },
    ]
    panel = pl.DataFrame(
        {
            "trade_date": ["2026-09-30"],
            "symbol": ["600328.SH"],
            "company_name": ["中盐化工"],
            "pb_percentile_10y": [12.0],
            "pb": [0.85],
            "pe_ttm": [15.0],
            "ma20_break": [True],
        }
    )
    # 1. 盈利期秋检：拦截
    res_prof = evaluate_trading_gates(
        pl.DataFrame(sep_rows_profitable), panel, {"basis_rate_pct": 1.5}, gates_cfg
    )
    assert res_prof["right_side_confirmation"]["triggered"] is False
    assert "判定为常规例行检修" in res_prof["right_side_confirmation"]["cond_seasonal_desc"]

    # 2. 亏损期秋检：通过
    sep_rows_loss = [dict(r) for r in sep_rows_profitable]
    sep_rows_loss[-1]["margin_regime"] = "deep_loss"
    res_loss = evaluate_trading_gates(
        pl.DataFrame(sep_rows_loss), panel, {"basis_rate_pct": 1.5}, gates_cfg
    )
    assert res_loss["right_side_confirmation"]["triggered"] is True
    assert "认可出清降负" in res_loss["right_side_confirmation"]["cond_seasonal_desc"]
