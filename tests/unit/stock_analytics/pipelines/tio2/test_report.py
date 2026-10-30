"""钛白粉研报渲染测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.pipelines.tio2.config import Tio2Config
from stock_analytics.pipelines.tio2.report import render_markdown


def test_render_markdown_empty() -> None:
    cfg = Tio2Config()
    md = render_markdown(
        panorama=pl.DataFrame(),
        projects=[],
        company_panel=None,
        episodes=[],
        gate_evaluation=None,
        config=cfg,
    )
    assert "无数据" in md


def test_render_markdown_with_data() -> None:
    cfg = Tio2Config()
    panorama = pl.DataFrame(
        {
            "report_month": ["2026-08"],
            "tio2_spot_price_cny": [15200.0],
            "delta_spot_price_cny": [200.0],
            "tio2_margin_cny": [1200.0],
            "margin_regime": ["profitable"],
            "export_qty_tons": [145000.0],
            "export_value_usd": [3.1e8],
            "export_qty_yoy": [18.5],
            "export_unit_price_usd": [2137.9],
            "inventory_flow_regime": ["genuine_terminal_destocking"],
            "cum_cap_expansion_w_tons": [43.0],
        }
    )
    projects = [
        {
            "plant_name": "攀枝花氯化法",
            "company": "龙佰集团",
            "province": "四川",
            "technology": "chloride_process",
            "capacity_w_tons": 20.0,
            "actual_start": "2023-03-15",
            "status": "operating",
        }
    ]
    comp_panel = pl.DataFrame(
        {
            "trade_date": ["2026-08-28"],
            "symbol": ["002601.SZ"],
            "company_name": ["龙佰集团"],
            "process_type": ["chloride_and_sulfate"],
            "role": ["integrated_oligopoly_leader"],
            "close": [18.5],
            "pb": [1.4],
            "pb_percentile_10y": [15.0],
            "pe_ttm": [14.0],
            "valuation_regime": ["deep_value_trough"],
            "net_profit_attr_p": [1.8e9],
        }
    )
    gates = {
        "left_side_odds": {
            "name": "寡头品左侧赔率建仓门禁",
            "triggered": True,
            "cond_loss_desc": "微利/亏损",
            "cond_pb_desc": "10Y PB 15%",
            "action": "建议建仓底仓",
        }
    }

    md = render_markdown(
        panorama=panorama,
        projects=projects,
        company_panel=comp_panel,
        episodes=[],
        gate_evaluation=gates,
        config=cfg,
    )

    assert "钛白粉 (TiO2) 全景基本面对账与周期量化研报" in md
    assert "攀枝花氯化法" in md
    assert "龙佰集团" in md
    assert "左侧赔率建仓门禁" in md
    assert "外需强劲终端真去库" in md
