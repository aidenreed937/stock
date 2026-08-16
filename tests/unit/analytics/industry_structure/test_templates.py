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


def test_human_report_surfaces_structure_radar_theme_types_and_rhythm() -> None:
    scores = {
        "industry_count": 8,
        "scored_industry_count": 8,
        "score_weights": ScoreWeights().as_dict(),
        "fundamental_blend": FundamentalBlendConfig().as_dict(),
        "fundamental_status_counts": {"stale_blended": 7, "official_stale": 1},
        "fast_fundamental_leaders": [],
        "top_structure": [
            {
                "industry_name": "煤炭",
                "score": 71.13,
                "structure_score": 71.13,
                "return_20d": 7.33,
                "return_60d": 5.52,
                "tcr": 0.52,
                "tags": "低估改善、相对占优",
            }
        ],
        "top_momentum": [],
        "low_valuation": [],
        "crowded_risk": [
            {
                "industry_name": "医药生物",
                "score": 52.91,
                "structure_score": 52.91,
                "return_20d": 8.88,
                "return_60d": 6.11,
                "tcr": 6.16,
                "tags": "强势主线、拥挤风险、相对占优",
            }
        ],
        "undervalued_improving": [],
        "strong_trends": [],
        "lagging_or_weak": [],
        "trend_diagnostics": {},
        "structure_health": {},
        "methodology": {},
    }
    manifest = {
        "as_of_date": "2026-08-14",
        "main_window": 20,
        "medium_windows": [60, 120],
        "run_id": "run_test",
    }
    panel = pl.DataFrame(
        [
            _panel_row(
                industry_name="煤炭",
                structure_score=71.13,
                structure_rank=1,
                return_5d=1.2,
                return_20d=7.33,
                return_60d=5.52,
                tcr=0.52,
                valuation_score=73.07,
                fundamental_score=75.34,
                momentum_score=70.0,
                crowding_temperature=30.89,
                tags="低估改善、相对占优",
            ),
            _panel_row(
                industry_name="医药生物",
                structure_score=52.91,
                structure_rank=4,
                return_5d=4.0,
                return_20d=8.88,
                return_60d=6.11,
                tcr=6.16,
                momentum_score=83.87,
                crowding_temperature=98.37,
                tags="强势主线、拥挤风险、相对占优",
            ),
            _panel_row(
                industry_name="电子",
                structure_score=41.64,
                structure_rank=27,
                return_5d=0.51,
                return_20d=2.55,
                return_60d=-1.90,
                tcr=29.10,
                pe_percentile_5y=86.46,
                pb_percentile_5y=92.32,
                crowding_temperature=60.20,
                tags="中性观察",
            ),
            _panel_row(
                industry_name="通信",
                structure_score=39.30,
                structure_rank=28,
                return_5d=5.10,
                return_20d=3.20,
                return_60d=-2.20,
                tcr=8.40,
                crowding_temperature=87.80,
                tags="拥挤风险",
            ),
            _panel_row(
                industry_name="综合",
                structure_score=67.91,
                structure_rank=3,
                return_5d=7.21,
                return_20d=10.00,
                return_60d=-4.86,
                tcr=0.16,
                fundamental_score=21.74,
                fundamental_status="official_stale",
                momentum_score=87.90,
                crowding_temperature=40.0,
                tags="强势主线、景气承压、相对占优",
            ),
            _panel_row(
                industry_name="有色金属",
                structure_score=63.25,
                structure_rank=4,
                return_5d=-3.70,
                return_20d=15.47,
                return_60d=-3.44,
                tcr=5.98,
                momentum_score=89.50,
                crowding_temperature=65.0,
                tags="强势主线、相对占优",
            ),
            _panel_row(
                industry_name="银行",
                structure_score=38.97,
                structure_rank=30,
                return_5d=0.30,
                return_20d=1.01,
                return_60d=1.55,
                tcr=1.39,
                pb_percentile_5y=13.05,
                dividend_yield=4.48,
                crowding_temperature=93.50,
                tags="拥挤风险",
            ),
            _panel_row(
                industry_name="食品饮料",
                structure_score=39.20,
                structure_rank=29,
                return_5d=-1.0,
                return_20d=-0.5,
                return_60d=-8.0,
                tcr=2.50,
                pe_percentile_5y=79.85,
                pb_percentile_5y=10.49,
                fundamental_score=24.18,
                crowding_temperature=90.24,
                tags="景气承压、拥挤风险",
            ),
        ]
    )

    human_report = render_human_report_markdown(
        config=_config(),
        manifest=manifest,
        scores=scores,
        facts=pl.DataFrame(),
        industry_panel=panel,
    )

    assert "## 结构雷达" in human_report
    assert "电子/TMT成交集中" in human_report
    assert "TMT合计TCR 37.50%" in human_report
    assert "## 主线类型" in human_report
    assert "低估改善、不拥挤、中期正收益: 煤炭" in human_report
    assert "成交主战场/高估值集中: 电子" in human_report
    assert "纯动量/基本面确认不足: 综合" in human_report
    assert "景气承压: 食品饮料" in human_report
    assert "## 短线节奏" in human_report
    assert "20日强但5日回落: 有色金属" in human_report
    assert "official_stale" not in human_report


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


def _panel_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "industry_code": "",
        "industry_name": "",
        "return_5d": None,
        "return_10d": None,
        "return_20d": None,
        "return_60d": None,
        "tcr": None,
        "pe_percentile_5y": None,
        "pb_percentile_5y": None,
        "dividend_yield": None,
        "momentum_score": None,
        "valuation_score": None,
        "fundamental_score": None,
        "fundamental_status": "",
        "crowding_temperature": None,
        "structure_score": None,
        "structure_rank": None,
        "tags": "",
    }
    row.update(overrides)
    return row
