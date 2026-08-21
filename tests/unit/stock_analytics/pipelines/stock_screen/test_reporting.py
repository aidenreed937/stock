"""个股排雷报告渲染测试。"""

import polars as pl

from stock_reporting.interpretation.stock_screen.config import StockScreenConfig
from stock_reporting.templates.stock_screen import render_report_markdown


def test_render_report_contains_counts_and_gaps() -> None:
    config = StockScreenConfig.from_mapping(
        {
            "title": "测试排雷",
            "hard_exclusion": {"rules": []},
            "yellow_warn": {"rules": []},
            "datasets": [],
        }
    )
    table = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "name": ["测试公司"],
            "level": ["excluded"],
            "rule_ids": [["st_marked"]],
            "reasons": [["st_marked: 名称 ST测试"]],
        }
    )

    markdown = render_report_markdown(
        config=config,
        manifest={"as_of_date": "2026-08-20"},
        summary={
            "population_size": 1,
            "excluded_count": 1,
            "warned_count": 0,
            "passed_count": 0,
            "data_gaps": [{"data_source": "tushare", "dataset": "forecast", "status": "missing"}],
            "missing_gates": [],
        },
        tables={"excluded": table, "warned": table.clear(), "passed": table.clear()},
    )

    assert "硬性剔除: 1" in markdown
    assert "000001.SZ" in markdown
    assert "tushare.forecast" in markdown
