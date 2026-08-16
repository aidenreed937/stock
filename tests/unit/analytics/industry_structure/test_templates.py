"""行业结构报告模板测试。"""

from pathlib import Path

import polars as pl

from stock.analytics.industry_structure.config import (
    FundamentalBlendConfig,
    IndustryStructureConfig,
    ScoreWeights,
)
from stock.analytics.industry_structure.templates import (
    render_human_report_markdown,
    render_report_markdown,
)


def test_render_reports_translate_fundamental_status_for_readers() -> None:
    scores = {
        "industry_count": 31,
        "scored_industry_count": 31,
        "score_weights": ScoreWeights().as_dict(),
        "fundamental_blend": FundamentalBlendConfig().as_dict(),
        "fundamental_status_counts": {"stale_blended": 30, "official_stale": 1},
        "fast_fundamental_leaders": [],
        "top_structure": [],
        "top_momentum": [],
        "low_valuation": [],
        "crowded_risk": [],
        "undervalued_improving": [],
        "strong_trends": [],
        "lagging_or_weak": [
            {
                "industry_name": "电子",
                "score": 41.64,
                "structure_score": 41.64,
                "return_20d": 2.55,
                "return_60d": -1.90,
                "tcr": 4.12,
                "tags": "中性观察",
            }
        ],
        "trend_diagnostics": {},
        "structure_health": {
            "level": "修复中但偏脆弱",
            "message": "短线行业扩散较强，但60日趋势和领先行业中期确认不足。",
            "scored_industry_count": 31,
            "positive_return_20d_count": 30,
            "positive_return_20d_share": 96.77,
            "positive_return_60d_count": 3,
            "positive_return_60d_share": 9.68,
            "top_limit": 10,
            "top_negative_60d_count": 9,
            "crowded_industry_count": 6,
            "crowded_industry_share": 19.35,
            "strong_trend_count": 3,
        },
        "methodology": {},
    }
    manifest = {
        "as_of_date": "2026-08-14",
        "main_window": 20,
        "medium_windows": [60, 120],
        "run_id": "run_test",
    }

    report = render_report_markdown(
        config=_config(),
        manifest=manifest,
        scores=scores,
        facts=pl.DataFrame(),
        industry_panel=pl.DataFrame(),
    )
    human_report = render_human_report_markdown(
        config=_config(),
        manifest=manifest,
        scores=scores,
        facts=pl.DataFrame(),
        industry_panel=pl.DataFrame(),
    )

    assert "stale_blended" not in report
    assert "official_stale" not in report
    assert "stale_blended" not in human_report
    assert "official_stale" not in human_report
    assert "财报已滞后，但已有预告/快报/研报辅助 30 个行业" in report
    assert "仅有已滞后的正式财报，缺少快速确认 1 个行业" in human_report
    assert "正式行业财报更新偏慢" in human_report
    assert "## 结构健康度" in human_report
    assert "- 健康度: 修复中但偏脆弱" in human_report
    assert "20日上涨行业 30/31" in human_report
    assert "### 落后方向" in report
    assert "## 落后方向" in human_report
    assert "- 落后方向: 电子" in human_report
    assert "| 电子 | 41.64 | 2.55 | -1.90 | 4.12 | 中性观察 |" in human_report


def _config() -> IndustryStructureConfig:
    return IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root=Path("data/analytics/industry_structure"),
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="SW2021",
        benchmark="000985",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )
