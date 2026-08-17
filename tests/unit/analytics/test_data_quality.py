"""分析口径与质量报告测试。"""

from datetime import date
from types import SimpleNamespace

import polars as pl

from stock.analytics.data_quality import build_quality_report
from stock.reporting.core.quality import render_quality_report_markdown


def test_quality_report_flags_hard_and_soft_issues() -> None:
    facts = pl.DataFrame(
        {
            "fact_id": [
                "window_20d",
                "watermark.tushare.stock_daily_bar",
                "watermark.tushare.moneyflow",
                "metric.future",
            ],
            "category": [
                "analysis_window",
                "data_watermark",
                "data_watermark",
                "metric_value",
            ],
            "dimension": ["meta", "technical", "fund_flow", "technical"],
            "data_source": ["tushare", "tushare", "tushare", "derived"],
            "dataset": ["stock_daily_bar", "stock_daily_bar", "moneyflow", "metrics"],
            "as_of_date": [date(2026, 8, 14)] * 4,
            "window": [20, 0, 0, 20],
            "metric_id": ["window_20d", "latest_trade_date", "latest_trade_date", "return_20d"],
            "value_float": [None, None, None, 1.0],
            "value_text": ["2026-07-20..2026-08-13", "2026-08-13", "2026-08-10", ""],
            "unit": ["", "", "", ""],
            "sample_size": [19, None, None, 1],
            "source": ["test", "test", "test", "test"],
            "status": ["insufficient", "lagging", "lagging", "ok"],
            "note": ["", "", "", "metric_date=2026-08-15"],
        }
    )
    datasets = (
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
            note="行情锚点",
        ),
        SimpleNamespace(
            data_source="tushare",
            dataset="moneyflow",
            dimension="fund_flow",
            required=False,
            date_column="",
            max_lag_days=2,
            static=False,
            cadence="trading_daily",
            quality_tier="confirming",
            note="资金流",
        ),
    )

    report = build_quality_report(
        title="测试报告",
        manifest={"as_of_date": "2026-08-14"},
        facts=facts,
        datasets=datasets,
        primary_data_source="tushare",
        primary_dataset="stock_daily_bar",
        main_window=20,
    )

    assert report["status"] == "failed"
    assert report["summary"]["error_count"] == 3
    assert report["summary"]["warning_count"] == 1
    markdown = render_quality_report_markdown(report)
    assert "口径与质量报告" in markdown
    assert "stock_daily_bar" in markdown
    assert "moneyflow" in markdown
    assert "晚于基准日的日期 2026-08-15" in markdown


def test_quality_report_flags_fact_as_of_mismatch() -> None:
    facts = pl.DataFrame(
        {
            "fact_id": ["window_20d"],
            "category": ["analysis_window"],
            "dimension": ["meta"],
            "data_source": ["tushare"],
            "dataset": ["stock_daily_bar"],
            "as_of_date": [date(2026, 8, 13)],
            "window": [20],
            "metric_id": ["window_20d"],
            "value_float": [None],
            "value_text": ["2026-07-17..2026-08-13"],
            "unit": [""],
            "sample_size": [20],
            "source": ["test"],
            "status": ["ok"],
            "note": [""],
        }
    )

    report = build_quality_report(
        title="测试报告",
        manifest={"as_of_date": "2026-08-14"},
        facts=facts,
        datasets=(),
        primary_data_source="tushare",
        primary_dataset="stock_daily_bar",
        main_window=20,
    )

    assert report["status"] == "failed"
    assert any(item["id"] == "fact_as_of_mismatch" for item in report["issues"])
