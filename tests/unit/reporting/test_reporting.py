"""展现与视图层 (stock.reporting) 单元测试。"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl

from stock.analytics.data_quality import build_quality_report
from stock.analytics.industry_structure.config import (
    FundamentalBlendConfig,
    IndustryStructureConfig,
    ScoreWeights,
)
from stock.analytics.market_temperature.config import MarketTemperatureConfig
from stock.analytics.models import DailyMarketScanSummary, MicroHealthSummary
from stock.reporting import (
    format_card_summary,
    format_console_report,
    format_investor_report,
    format_pro_report,
    human_watermark_issue_lines,
    human_watermark_latest_text,
    render_industry_structure_human_report_markdown,
    render_industry_structure_markdown,
    render_investor_brief_markdown,
    render_market_temperature_human_report_markdown,
    render_market_temperature_markdown,
    render_quality_report_markdown,
)


def test_watermark_rendering() -> None:
    rows = [
        {
            "data_source": "tushare",
            "dataset": "stock_daily_bar",
            "status": "ok",
            "value_text": "2026-08-14",
            "note": "A股全市场行情",
        },
        {
            "data_source": "tushare",
            "dataset": "margin",
            "status": "lagging",
            "value_text": "2026-08-13",
            "note": "两融数据",
        },
    ]
    issues = human_watermark_issue_lines(rows)
    assert len(issues) >= 1
    assert any("两融数据" in line for line in issues)

    latest_text = human_watermark_latest_text(rows)
    assert "A股全市场行情" in latest_text
    assert "2026-08-14" in latest_text


def test_quality_report_rendering() -> None:
    facts = pl.DataFrame(
        {
            "fact_id": ["window_20d"],
            "category": ["analysis_window"],
            "dimension": ["meta"],
            "data_source": ["tushare"],
            "dataset": ["stock_daily_bar"],
            "as_of_date": [date(2026, 8, 14)],
            "window": [20],
            "metric_id": ["window_20d"],
            "value_float": [None],
            "value_text": ["2026-07-20..2026-08-14"],
            "unit": [""],
            "sample_size": [20],
            "source": ["test"],
            "status": ["ok"],
            "note": [""],
        }
    )
    report = build_quality_report(
        title="测试体检",
        manifest={"as_of_date": "2026-08-14"},
        facts=facts,
        datasets=(
            SimpleNamespace(
                data_source="tushare",
                dataset="stock_daily_bar",
                dimension="technical",
                required=True,
                date_column="",
                max_lag_days=0,
                static=False,
                cadence="trading_daily",
                quality_tier="core",
                note="行情",
            ),
        ),
        primary_data_source="tushare",
        primary_dataset="stock_daily_bar",
        main_window=20,
    )
    md = render_quality_report_markdown(report)
    assert "# 测试体检口径与质量报告" in md
    assert "数据水位" in md


def test_scan_report_formatting() -> None:
    summary = DailyMarketScanSummary(
        trade_date=date(2026, 8, 14),
        one_sentence_summary="保持 80% 仓位，优选低估资产。",
        signals=[],
        undervalued_industries=["银行", "非银金融"],
        crowded_industries=["电子"],
        top1_industry="电子",
        top1_tcr=25.0,
        micro_health=MicroHealthSummary(
            margin_ratio=2.1,
            margin_status="杠杆出清",
            pb_break_ratio=8.5,
            pb_break_status="大面积折价",
            turnover_ratio=3.2,
            turnover_status="情绪中性",
            above_ma60_ratio=50.0,
            ma60_status="修复中",
        ),
        action_items=["- ✅ 保持 70~90% 仓位", "- ❌ 不追高"],
    )

    investor_md = format_investor_report(summary)
    assert "A 股每日体检" in investor_md
    assert "银行" in investor_md

    pro_md = format_pro_report(summary)
    assert "A 股量化全景体检专业报告" in pro_md

    card_text = format_console_report(summary)
    assert "A 股量化体检全景摘要" in card_text
    assert format_card_summary(summary) == card_text


def test_investor_brief_rendering() -> None:
    brief = {
        "title": "A 股市场投资决策简报",
        "manifest": {
            "as_of_date": "2026-08-14",
            "inputs": {
                "market_temperature": {"run_id": "run_market_001"},
                "industry_structure": {"run_id": "run_industry_001"},
            },
        },
        "participation": {
            "stance": "可以谨慎参与",
            "action": "控制仓位，精选行业",
            "risk_level": "中等",
            "reasons": ["综合温度处于中性区间", "行业扩散较好"],
        },
        "market_snapshot": {
            "composite_temperature": 55.0,
        },
        "industry_snapshot": {
            "structure_health": {"level": "温和修复"},
        },
        "candidate_industries": [
            {
                "industry_name": "银行",
                "structure_score": 75.0,
                "return_20d": 3.5,
                "return_60d": 6.2,
                "crowding_temperature": 45.0,
                "reason": "低估值且稳健",
            }
        ],
        "risk_industries": [],
        "lagging_industries": [],
        "reading_notes": ["注意仓位管理"],
    }
    md = render_investor_brief_markdown(brief)
    assert "# A 股市场投资决策简报" in md
    assert "能不能参与" in md
    assert "银行" in md


def test_market_temperature_templates_rendering() -> None:
    config = MarketTemperatureConfig(
        schema_version=1,
        title="测试市场温度计",
        artifact_root=Path("data/analytics/market_temperature"),
        main_window=20,
        short_windows=(5, 10),
        dimensions=(),
        datasets=(),
    )
    manifest = {
        "as_of_date": "2026-08-14",
        "main_window": 20,
        "short_windows": [5, 10],
        "run_id": "run_test_001",
    }
    scores = {
        "composite": {"status": "ready", "temperature": 60.5, "reason": "整体中性偏热"},
        "systemic_risk": {"level": "低", "message": "无系统性风险"},
        "dimensions": [
            {
                "name": "估值面",
                "dimension_id": "valuation",
                "weight": 0.25,
                "temperature": 58.0,
                "status": "ready",
                "ok_metric_count": 3,
                "metric_count": 3,
                "reason": "估值适中",
            }
        ],
    }
    facts = pl.DataFrame()
    md = render_market_temperature_markdown(
        config=config, manifest=manifest, scores=scores, facts=facts
    )
    assert "# 测试市场温度计" in md
    assert "综合温度" in md

    human_md = render_market_temperature_human_report_markdown(
        config=config, manifest=manifest, scores=scores, facts=facts
    )
    assert "# 测试市场温度计人工阅读版" in human_md
    assert "一句话结论" in human_md


def test_industry_structure_templates_rendering() -> None:
    config = IndustryStructureConfig(
        schema_version=1,
        title="测试申万行业结构",
        artifact_root=Path("data/analytics/industry_structure"),
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="sw_2021",
        benchmark="000300.SH",
        score_weights=ScoreWeights(momentum=0.4, valuation=0.25, fundamental=0.15, crowding=0.20),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )
    manifest = {
        "as_of_date": "2026-08-14",
        "main_window": 20,
        "medium_windows": [60, 120],
        "run_id": "run_ind_001",
    }
    scores = {
        "industry_count": 31,
        "scored_industry_count": 31,
        "score_weights": {"momentum": 0.4, "valuation": 0.3},
        "trend_diagnostics": {"message": "大部分行业处于上升通道"},
        "structure_health": {"level": "良好", "message": "扩散健康"},
        "fundamental_status_counts": {},
        "top_structure": [],
        "crowded_risk": [],
        "lagging_or_weak": [],
    }
    facts = pl.DataFrame()
    panel = pl.DataFrame()
    md = render_industry_structure_markdown(
        config=config, manifest=manifest, scores=scores, facts=facts, industry_panel=panel
    )
    assert "# 测试申万行业结构" in md
    assert "趋势诊断" in md

    human_md = render_industry_structure_human_report_markdown(
        config=config, manifest=manifest, scores=scores, facts=facts, industry_panel=panel
    )
    assert "# 测试申万行业结构人工阅读版" in human_md
    assert "一句话结论" in human_md
