"""宏观极值下穿申万二级行业机会与风险：单元测试。"""

from datetime import date
from unittest.mock import patch

import polars as pl

from stock_reporting.interpretation.macro_risk.meso_penetration import (
    build_meso_penetration_section,
)
from stock_reporting.templates.macro_risk_report import render_macro_risk_report


def _synthetic_l2_panel() -> pl.DataFrame:
    """构造合成申万二级行业切片。"""
    d = date(2026, 10, 16)
    return pl.DataFrame(
        [
            # 1. 狂热暴雷标的：高拥挤 + 高估值
            {
                "trade_date": d,
                "industry_code": "270100",
                "industry_name": "半导体",
                "crowding_score": 95.0,
                "pe_ttm_ew_percentile_5y": 92.0,
                "return_20d": 12.0,
                "return_60d": 35.0,
                "revenue_growth_ttm": 0.15,
                "profit_growth_ttm": 0.25,
                "cip_yoy": 10.0,
                "cip_to_fa_ratio": 0.20,
            },
            # 2. 狂热安全岛标的：低拥挤 + 低估值
            {
                "trade_date": d,
                "industry_code": "220200",
                "industry_name": "化学原料",
                "crowding_score": 15.0,
                "pe_ttm_ew_percentile_5y": 18.0,
                "return_20d": -1.0,
                "return_60d": 2.0,
                "revenue_growth_ttm": 0.02,
                "profit_growth_ttm": 0.05,
                "cip_yoy": 5.0,
                "cip_to_fa_ratio": 0.15,
            },
            # 3. 恐慌真黄金坑：超跌 + 营收净利双正 + 无Capex过剩
            {
                "trade_date": d,
                "industry_code": "730200",
                "industry_name": "通信设备",
                "crowding_score": 45.0,
                "pe_ttm_ew_percentile_5y": 40.0,
                "return_20d": -18.0,
                "return_60d": -10.0,
                "revenue_growth_ttm": 0.20,
                "profit_growth_ttm": 0.35,
                "cip_yoy": 8.0,
                "cip_to_fa_ratio": 0.18,
            },
            # 4. 恐慌假黄金坑/飞刀：超跌但在建工程暴增
            {
                "trade_date": d,
                "industry_code": "630500",
                "industry_name": "光伏设备",
                "crowding_score": 50.0,
                "pe_ttm_ew_percentile_5y": 60.0,
                "return_20d": -25.0,
                "return_60d": -35.0,
                "revenue_growth_ttm": -0.05,
                "profit_growth_ttm": -0.40,
                "cip_yoy": 45.0,
                "cip_to_fa_ratio": 0.42,
            },
            # 5. 恐慌避险主线：逆势走强 + 净利高增 + 无Capex过剩
            {
                "trade_date": d,
                "industry_code": "720500",
                "industry_name": "医疗服务",
                "crowding_score": 55.0,
                "pe_ttm_ew_percentile_5y": 42.0,
                "return_20d": 12.0,
                "return_60d": 18.0,
                "revenue_growth_ttm": 0.18,
                "profit_growth_ttm": 0.65,
                "cip_yoy": 6.0,
                "cip_to_fa_ratio": 0.12,
            },
        ]
    )


def test_meso_penetration_silent_in_normal_regime() -> None:
    """平稳水温下自动静默，不污染宏观日报精简视图。"""
    res = build_meso_penetration_section(
        target_date=date(2026, 10, 16),
        overheat_val=50.0,
        panic_val=40.0,
        force_preview=False,
    )
    assert res == ""


@patch(
    "stock_reporting.interpretation.macro_risk.meso_penetration._load_l2_panel_slice",
    return_value=_synthetic_l2_panel(),
)
def test_meso_penetration_overheat_triggered(mock_load) -> None:
    """狂热超标时自动触发高位暴雷排雷与低位安全承接榜。"""
    res = build_meso_penetration_section(
        target_date=date(2026, 10, 16),
        overheat_val=75.0,
        panic_val=30.0,
    )
    assert "## 宏观极值下穿：申万二级行业机会与风险清单" in res
    assert "狂热极值排雷：高位抱团过热名单" in res
    assert "半导体" in res
    assert "低位安全承接名单" in res
    assert "化学原料" in res


@patch(
    "stock_reporting.interpretation.macro_risk.meso_penetration._load_l2_panel_slice",
    return_value=_synthetic_l2_panel(),
)
def test_meso_penetration_panic_triggered(mock_load) -> None:
    """恐慌超标时自动触发超跌错杀真黄金坑验真、逆势避险主线与假飞刀排雷。"""
    res = build_meso_penetration_section(
        target_date=date(2026, 10, 16),
        overheat_val=20.0,
        panic_val=80.0,
    )
    assert "## 宏观极值下穿：申万二级行业机会与风险清单" in res
    assert "超跌错杀「真黄金坑」名单" in res
    assert "通信设备" in res
    assert "逆势走强「避险主线」名单" in res
    assert "医疗服务" in res
    assert "假黄金坑/飞刀」名单" in res
    assert "光伏设备" in res


def test_macro_risk_report_integration_contains_meso_on_extremes() -> None:
    """验证宏观风控日报在极值状态下成功挂载中观下穿卡片。"""
    d = date(2026, 10, 16)
    df = pl.DataFrame(
        [
            {
                "trade_date": d,
                "overheat_index": 78.0,  # 狂热超标
                "panic_index": 25.0,
                "dim_leverage": 60.0,
                "dim_crowding": 70.0,
                "dim_fear": 30.0,
                "dim_valuation": 40.0,
                "dim_capital": 20.0,
                "dim_cross_asset": 50.0,
            }
        ]
    )

    with patch(
        "stock_reporting.interpretation.macro_risk.meso_penetration._load_l2_panel_slice",
        return_value=_synthetic_l2_panel(),
    ):
        report = render_macro_risk_report(df, target_date=d, template="simple")
        assert "## 宏观极值下穿：申万二级行业机会与风险清单" in report
        assert "狂热极值排雷" in report
