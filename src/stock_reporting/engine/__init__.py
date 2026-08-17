"""Jinja2 Markdown 渲染引擎模块。"""

from __future__ import annotations

from stock_reporting.engine.filters import (
    format_currency_wan,
    format_currency_yi,
    format_decimal,
    format_pct,
    register_filters,
    render_markdown_table,
)
from stock_reporting.engine.renderer import ReportRenderer

__all__ = [
    "ReportRenderer",
    "format_currency_wan",
    "format_currency_yi",
    "format_decimal",
    "format_pct",
    "register_filters",
    "render_markdown_table",
]
