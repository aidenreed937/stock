"""全球宏观与海外利率观察模块单元测试。"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock_reporting.interpretation.macro_risk.global_macro_hint import (
    build_global_macro_hint,
)
from stock_reporting.templates.macro_risk_report import render_macro_risk_report


def test_build_global_macro_hint_missing_file_returns_none(tmp_path: Path) -> None:
    hint = build_global_macro_hint(
        target_date=date(2026, 10, 9),
        mart_path=tmp_path / "non_existent.parquet",
    )
    assert hint is None


def test_build_global_macro_hint_dynamic_evaluation(tmp_path: Path) -> None:
    test_mart = tmp_path / "global_macro_daily.parquet"
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 8), date(2026, 10, 9)],
            "us_10y_yield": [5.15, 5.27],
            "us_2y_yield": [4.80, 4.79],
            "us_yield_curve_10y_2y": [0.35, 0.48],
            "cn_10y_yield": [1.68, 1.69],
        }
    )
    df.write_parquet(test_mart)

    hint = build_global_macro_hint(
        target_date=date(2026, 10, 9),
        row_dict={"copper_gold_score": 38.98},
        mart_path=test_mart,
    )

    assert hint is not None
    assert len(hint.items) == 4

    names = [item.name for item in hint.items]
    assert "美债 10 年期收益率" in names
    assert "美债 10Y - 2Y 期限利差" in names
    assert "中美 10Y 国债利差" in names
    assert "全球工业景气 (铜金比)" in names

    # 动态数值与定性校验
    us10y_item = next(it for it in hint.items if it.name == "美债 10 年期收益率")
    assert us10y_item.display_value == "5.27%"
    assert us10y_item.badge == "🔴"
    assert "站上 5%" in us10y_item.comment

    spread_item = next(it for it in hint.items if it.name == "中美 10Y 国债利差")
    assert spread_item.display_value == "-358 bps"
    assert spread_item.badge == "🔴"

    curve_item = next(it for it in hint.items if it.name == "美债 10Y - 2Y 期限利差")
    assert curve_item.display_value == "+0.48%"
    assert curve_item.badge == "⚪"

    cg_item = next(it for it in hint.items if it.name == "全球工业景气 (铜金比)")
    assert cg_item.display_value == "39.0 分位"
    assert "黄金避险占优" in cg_item.comment

    assert "全球无风险折现率高位运行" in hint.summary


def test_render_macro_risk_report_includes_global_macro_section() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 9)],
            "overheat_index": [64.2],
            "panic_index": [35.1],
            "dim_valuation": [36.4],
            "dim_leverage": [74.1],
            "dim_fear": [26.1],
            "dim_crowding": [74.6],
            "dim_breadth": [41.4],
            "dim_flow": [37.9],
            "copper_gold_score": [38.98],
            "ffr_chg_6m_score": [60.53],
        }
    )
    md = render_macro_risk_report(df, date(2026, 10, 9))
    assert "全球宏观与海外利率观察" in md
    assert "政策利率周期风险提示" in md
    assert "美债 10 年期收益率" in md


def test_build_global_macro_hint_oil_dynamic_regimes(tmp_path: Path) -> None:
    """测试原油价格在极端高位、中枢均衡、低位缓和不同情境下的动态评级与机制解读。"""
    test_mart = tmp_path / "global_macro_daily.parquet"

    # 1. 模拟极端高位与价差收窄 (类似 2026-10-20 截面)
    dates = [date(2026, 9, 20) + timedelta(days=i) for i in range(25)]
    wti_series = [95.0 + i * 0.5 for i in range(25)]  # ~95 上涨至 ~107
    brent_series = [125.0 - i * 0.4 for i in range(25)]  # ~125 收敛至 ~115 (价差收窄)

    df_high = pl.DataFrame(
        {
            "trade_date": dates,
            "us_10y_yield": [4.96] * 25,
            "cn_10y_yield": [1.64] * 25,
            "crude_oil_price": wti_series,
            "brent_crude_oil_price": brent_series,
        }
    )
    df_high.write_parquet(test_mart)

    hint_high = build_global_macro_hint(
        target_date=dates[-1],
        mart_path=test_mart,
    )
    assert hint_high is not None
    oil_item_high = next(it for it in hint_high.items if "原油价格" in it.name)
    assert oil_item_high.badge == "🔴"
    assert "百元极端高位" in oil_item_high.comment
    assert "Brent-WTI 价差显著收窄" in oil_item_high.comment
    assert "大宗原油高位运行加剧全球再通胀黏性" in hint_high.summary

    # 2. 模拟常态中枢均衡 (油价 75 美元，价差平稳)
    df_mid = pl.DataFrame(
        {
            "trade_date": dates,
            "us_10y_yield": [4.0] * 25,
            "cn_10y_yield": [2.5] * 25,
            "crude_oil_price": [72.0] * 25,
            "brent_crude_oil_price": [76.0] * 25,
        }
    )
    df_mid.write_parquet(test_mart)
    hint_mid = build_global_macro_hint(target_date=dates[-1], mart_path=test_mart)
    assert hint_mid is not None
    oil_item_mid = next(it for it in hint_mid.items if "原油价格" in it.name)
    assert oil_item_mid.badge == "⚪"
    assert "常态均衡中枢" in oil_item_mid.comment
    assert "中性区间" in hint_mid.summary

    # 3. 模拟偏低区间 (油价 60 美元)
    df_low = pl.DataFrame(
        {
            "trade_date": dates,
            "us_10y_yield": [4.0] * 25,
            "cn_10y_yield": [2.5] * 25,
            "crude_oil_price": [58.0] * 25,
            "brent_crude_oil_price": [62.0] * 25,
        }
    )
    df_low.write_parquet(test_mart)
    hint_low = build_global_macro_hint(target_date=dates[-1], mart_path=test_mart)
    assert hint_low is not None
    oil_item_low = next(it for it in hint_low.items if "原油价格" in it.name)
    assert oil_item_low.badge == "🟢"
    assert "偏低区间" in oil_item_low.comment
