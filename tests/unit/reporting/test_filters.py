"""Reporting Filter 单元测试。"""

from __future__ import annotations

import polars as pl

from stock.reporting.engine.filters import (
    format_currency_wan,
    format_currency_yi,
    format_decimal,
    format_pct,
    render_markdown_table,
)


def test_format_pct() -> None:
    assert format_pct(0.0523) == "+5.23%"
    assert format_pct(-0.0034) == "-0.34%"
    assert format_pct(0.0, signed=False) == "0.00%"
    assert format_pct(None) == "-"
    assert format_pct(0.12345, digits=3) == "+12.345%"


def test_format_decimal() -> None:
    assert format_decimal(1234567.89) == "1,234,567.89"
    assert format_decimal(-12.345, digits=1) == "-12.3"
    assert format_decimal(42.5, signed=True) == "+42.50"
    assert format_decimal(None) == "-"


def test_format_currency() -> None:
    assert format_currency_yi(18200000000) == "182.00 亿"
    assert format_currency_yi(None) == "-"
    assert format_currency_wan(500000) == "50.00 万"
    assert format_currency_wan(None) == "-"


def test_render_markdown_table_dicts() -> None:
    data = [
        {"代码": "510300.SH", "名称": "沪深300ETF", "涨跌幅": "+0.45%"},
        {"代码": "512880.SH", "名称": "证券ETF", "涨跌幅": "+1.82%"},
    ]
    md = render_markdown_table(data, alignments={"涨跌幅": "right"})
    assert "| 代码 | 名称 | 涨跌幅 |" in md
    assert "| --- | --- | ---: |" in md
    assert "| 510300.SH | 沪深300ETF | +0.45% |" in md


def test_render_markdown_table_dataframe() -> None:
    df = pl.DataFrame(
        {
            "industry": ["电子", "银行"],
            "pe": [25.4, 6.2],
        }
    )
    md = render_markdown_table(df, headers=["industry", "pe"])
    assert "| industry | pe |" in md
    assert "| 电子 | 25.4 |" in md


def test_render_markdown_table_empty() -> None:
    assert render_markdown_table([]) == "*暂无数据*"
    assert render_markdown_table(None) == "*暂无数据*"
    assert render_markdown_table(pl.DataFrame()) == "*暂无数据*"
