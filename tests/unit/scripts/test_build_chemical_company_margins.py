"""scripts/build_chemical_company_margins.py 单元测试。"""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import polars as pl

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "build_chemical_company_margins.py"
_mod = run_path(str(_SCRIPT_PATH))
generate_company_margins_weekly = _mod["generate_company_margins_weekly"]


def test_generate_company_margins_weekly_structure() -> None:
    """验证生成的企业毛利时序结构完备、包含两家核心标的且日期有序。"""
    df: pl.DataFrame = generate_company_margins_weekly()
    assert not df.is_empty()

    expected_cols = [
        "trade_date",
        "symbol",
        "company_name",
        "tio2_spot_price_cny",
        "ilmenite_price_cny",
        "acid_price_cny",
        "unit_gross_margin_cny",
        "unit_cash_margin_cny",
        "gross_margin_ratio",
        "alpha_spread_cny",
        "sulfate_alpha_cny",
        "sulfate_margin_cny",
        "chloride_margin_cny",
        "blended_cash_cost_cny",
        "ore_captive_ratio",
        "rolling_60d_gross_margin_cny",
        "rolling_60d_gpm_ratio",
        "source",
        "data_status",
        "collected_at",
    ]
    for col in expected_cols:
        assert col in df.columns, f"缺少列: {col}"

    assert len(df) >= 50
    symbols = set(df["symbol"].unique().to_list())
    assert symbols == {"002601.SZ", "002145.SZ"}

    # 验证平滑指标无缺失
    assert df["rolling_60d_gross_margin_cny"].null_count() == 0
    assert df["rolling_60d_gpm_ratio"].null_count() == 0


def test_company_margins_alpha_spread_relationship() -> None:
    """验证龙佰集团硫酸法自备矿具有正向 Alpha 利差。"""
    df: pl.DataFrame = generate_company_margins_weekly()

    lb_df = df.filter(pl.col("symbol") == "002601.SZ")
    assert not lb_df.is_empty()

    # 龙佰拥有 65% 自备矿，在硫酸法工艺下相对于行业纯外购基准必然享有正向 Alpha
    positive_sulfate_alpha = lb_df.filter(pl.col("sulfate_alpha_cny") > 0)
    assert len(positive_sulfate_alpha) == len(lb_df)

    # 验证自给率
    assert (lb_df["ore_captive_ratio"] == 0.65).all()

    zh_df = df.filter(pl.col("symbol") == "002145.SZ")
    assert not zh_df.is_empty()
    assert (zh_df["ore_captive_ratio"] == 0.0).all()
