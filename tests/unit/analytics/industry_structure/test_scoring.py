"""行业结构评分测试。"""

from datetime import date

import polars as pl

from stock.analytics.industry_structure.config import (
    FundamentalBlendConfig,
    IndustryStructureConfig,
    ScoreWeights,
)
from stock.analytics.industry_structure.scoring import score_industry_panel


def test_score_industry_panel_adds_ranks_and_tags() -> None:
    panel = pl.DataFrame(
        {
            "industry_code": ["801001.SI", "801002.SI", "801003.SI", "801004.SI"],
            "industry_name": ["强行业", "便宜行业", "弱行业", "流出行业"],
            "as_of_date": [date(2026, 8, 14)] * 4,
            "fundamental_date": [date(2026, 3, 31)] * 4,
            "return_5d": [5.0, 1.0, -2.0, -3.0],
            "return_20d": [20.0, 2.0, -10.0, -15.0],
            "return_60d": [35.0, 8.0, -20.0, -25.0],
            "relative_return_20d": [15.0, 1.0, -12.0, -18.0],
            "ma_bias_20d": [8.0, 0.5, -6.0, -8.0],
            "tcr": [18.0, 6.0, 3.0, 2.0],
            "tcr_percentile": [90.0, 30.0, 10.0, 5.0],
            "money_net_inflow_share_20d": [5.0, 1.0, -0.1, -5.0],
            "large_money_net_inflow_share_20d": [4.0, 0.5, -0.2, -4.0],
            "money_net_inflow_share_5d": [6.0, 0.5, -0.5, -6.0],
            "pe_percentile_5y": [80.0, 10.0, 40.0, 60.0],
            "pb_percentile_5y": [70.0, 15.0, 35.0, 65.0],
            "pbroe_residual": [0.5, -0.5, 0.0, 0.8],
            "revenue_growth_percentile": [70.0, 65.0, 20.0, 10.0],
            "profit_growth_percentile": [75.0, 70.0, 15.0, 8.0],
            "roe_percentile": [80.0, 60.0, 25.0, 5.0],
            "forecast_positive_share": [90.0, 50.0, 10.0, 0.0],
            "forecast_p_change_mid_median": [120.0, 20.0, -30.0, -50.0],
            "express_profit_growth_median": [80.0, 30.0, -20.0, -40.0],
            "express_roe_median": [10.0, 8.0, 3.0, 1.0],
            "report_rc_revision_ratio": [70.0, 55.0, 20.0, 5.0],
        }
    )

    scored, scores = score_industry_panel(_config(), panel)

    assert scored.height == 4
    assert scored["structure_rank"].drop_nulls().min() == 1
    assert scores["industry_count"] == 4
    assert scores["top_structure"]
    assert scores["methodology"]["field_definitions"]["tcr"].startswith("TCR=最近20")
    assert scores["fundamental_blend"]["stale_fast_weight"] == 0.6
    assert scores["fundamental_status_counts"]["stale_blended"] == 4
    assert scores["trend_diagnostics"]["status"] in {
        "neutral",
        "localized_strength_weak_breadth",
        "short_rebound_medium_unconfirmed",
        "trend_confirming",
    }
    assert scores["structure_health"]["level"] in {
        "健康",
        "中性修复",
        "修复中但偏脆弱",
        "偏脆弱",
        "偏弱",
    }
    cheap = scored.filter(pl.col("industry_name") == "便宜行业").to_dicts()[0]
    crowded = scored.filter(pl.col("industry_name") == "强行业").to_dicts()[0]
    outflow = scored.filter(pl.col("industry_name") == "流出行业").to_dicts()[0]
    assert crowded["fundamental_status"] == "stale_blended"
    assert crowded["fundamental_fast_weight"] == 0.6
    assert crowded["fund_flow_score"] == 100.0
    assert "低估改善" in cheap["tags"]
    assert "拥挤风险" in crowded["tags"]
    assert "资金确认" in crowded["tags"]
    assert "资金流出压力" in outflow["tags"]
    assert scores["crowded_risk"]
    assert scores["fund_flow_confirmed"]
    assert scores["fund_flow_pressure"]
    assert scores["top_fund_flow"]


def _config() -> IndustryStructureConfig:
    return IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root="data/analytics/industry_structure",
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="SW2021",
        benchmark="000985",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )
