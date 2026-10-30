"""纯碱全景研报数据驱动渲染测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.soda_ash.config import SodaAshConfig
from stock_analytics.pipelines.soda_ash.report import render_markdown


def _panorama() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-01", "2026-02"],
            "soda_output_w_tons": [200.0, 210.0],
            "soda_output_yoy": [5.0, 6.0],
            "glass_output_w_cases": [7000.0, 7100.0],
            "glass_output_yoy": [3.0, 4.0],
            "scissors_spread_yoy": [-2.0, -2.0],
            "warehouse_receipt_month_end": [100.0, 110.0],
            "factory_inv_month_end_w_tons": [90.0, 95.0],
            "latest_shipment_rate_pct": [99.0, 98.0],
            "survey_shipment_rate_pct": [99.0, 98.0],
            "survey_operating_rate_pct": [80.0, 80.0],
            "double_ton_margin_cny": [50.0, 40.0],
            "margin_regime": ["near_breakeven", "near_breakeven"],
            "futures_settle_month_end": [1700.0, 1700.0],
            "soda_spot_price_cny": [1800.0, 1780.0],
            "basis_month_end": [100.0, 80.0],
            "top20_net_long_vol": [1000.0, 1100.0],
            "smart_money_bias": ["neutral", "neutral"],
            "cap_increment_w_tons": [0.0, 0.0],
            "cum_cap_expansion_w_tons": [150.0, 150.0],
            "delta_factory_inv_w_tons": [None, 5.0],
            "delta_warehouse_receipt": [None, 10.0],
            "inventory_flow_regime": ["genuine_terminal_destocking", "passive_accumulation"],
        }
    )


def _company_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": ["2026-01-30", "2026-01-30"],
            "symbol": ["600328.SH", "000683.SZ"],
            "company_name": ["中盐化工", "远兴能源"],
            "process_type": ["solvay_and_hou", "natural_alkali"],
            "fin_report_date": ["2025-09-30", "2025-09-30"],
            "total_revenue": [1.0e10, 8.0e9],
            "net_profit_attr_p": [-2.0e8, 1.0e9],
            "assets_impair_loss": [1.0e7, 0.0],
            "inventories": [1.0e9, 5.0e8],
            "soda_revenue_share_approx": [0.49, 0.65],
            "close": [8.0, 12.0],
            "total_mv": [8.0e10, 4.0e10],
            "pb": [0.79, 3.0],
            "pb_percentile_10y": [1.7, 60.0],
            "pe_ttm": [-20.0, 15.0],
            "valuation_regime": ["deep_value_trough", "fair_expansion"],
        }
    )


def test_render_markdown_empty_panorama() -> None:
    text = render_markdown(
        pl.DataFrame(),
        [],
        None,
        None,
        [],
        None,
        SodaAshConfig(),
    )
    assert "无数据" in text


def test_render_markdown_sections_and_company_narrative() -> None:
    episodes = [
        {
            "kind": "high_profit",
            "label": "高利润顶部区",
            "start": "2021-07",
            "end": "2021-09",
            "months_count": 3,
            "margin_mean": 1200.0,
            "margin_min": 1100.0,
            "margin_max": 1400.0,
            "spot_min": 3200.0,
            "spot_max": 3600.0,
            "scissors_first": 5.0,
            "scissors_last": -3.0,
            "transition_note": "后续利润回落 -800 元/吨",
        }
    ]
    gate_evaluation = {
        "left_side_odds": {
            "triggered": True,
            "cond_margin_desc": "理论利润状态: `deep_loss`",
            "cond_pb_desc": "全池最低 PB 10Y 分位: `1.7%` (中盐化工 (600328.SH))",
            "cond_role_pb_desc": "门禁指定角色 (远兴能源 (000683.SZ)) 最低 PB 10Y 分位: `60.0%` → 未满足",
            "suggestion": "满足左侧赔率建仓门禁",
        },
        "right_side_confirmation": {
            "triggered": False,
            "cond_op_desc": "周度开工率: `70.0%`",
            "cond_destock_desc": "中游蓄水池: `genuine_terminal_destocking` (连续去库 1 期，需 >= 3 期)",
            "cond_basis_desc": "期现基差率: `+1.00%`",
            "cond_demand_desc": "需求共振校验: 剪刀差 +2.5%",
            "cond_ma_desc": "MA20 突破: 未确认",
            "suggestion": "未满足右侧确认门禁",
        },
        "top_escape": {
            "triggered": False,
            "warning": False,
            "match_count": 1,
            "trigger_match_count_min": 3,
            "cond_op_desc": "行业开工负荷打满: 否 (开工率 80.0%，阈值 >= 88%)",
            "cond_margin_desc": "理论利润超额暴利: 否 (状态 `near_breakeven`)",
            "cond_flow_desc": "中游逆势被动累库: 否 (状态 `passive_accumulation`)",
            "cond_pe_desc": "静态低 PE 见顶陷阱: 否 (最低 PE-TTM 15.00，阈值 <= 8x)",
            "cond_divergence_desc": "高估值 + 内外需背离: 否 (全池最低 PB 10Y 分位 1.7%，阈值 >= 60%)",
            "suggestion": "未触发顶部逃顶门禁",
        },
    }
    text = render_markdown(
        _panorama(),
        [
            {
                "company": "远兴能源",
                "plant_name": "阿拉善一期",
                "capacity_w_tons": 500.0,
                "technology": "天然碱",
                "status": "已投产",
                "actual_start": "2023-06",
                "source": "公告",
            }
        ],
        _company_panel(),
        {
            "sa_heavy_price": 1800.0,
            "futures_sa0_settle": 1700.0,
            "basis_cny": 100.0,
            "basis_rate_pct": 5.88,
        },
        episodes,
        gate_evaluation,
        SodaAshConfig(),
    )
    # 数据驱动历史拐点：无硬编码 2021Q3 文案，只有检测到的区间
    assert "2021-07 ~ 2021-09" in text
    assert "## 五、" in text
    assert "中盐化工" in text
    assert "远兴能源" in text
    assert "## 六、" in text
    assert "满足左侧赔率建仓门禁" in text
    assert "2021Q3" not in text
    # 逃顶条件对账来自评估结果，渲染层不得硬编码
    assert "行业开工负荷打满: 否" in text
    assert "[1/3 因子]" in text
    assert "None" not in text.split("## 六、", 1)[1]
    # 产能累计口径提示：仅累计 actual_start
    assert "累计跟踪**已投达产**有效产能变动" in text


def test_render_markdown_no_gate_section_when_missing() -> None:
    text = render_markdown(
        _panorama(),
        [],
        None,
        None,
        [],
        None,
        SodaAshConfig(),
    )
    assert "## 六、" not in text
