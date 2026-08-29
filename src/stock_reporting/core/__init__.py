"""Reporting 核心基础组件。"""

from __future__ import annotations

from stock_reporting.core.matplotlib_config import configure_matplotlib
from stock_reporting.core.quality import render_quality_report_markdown
from stock_reporting.core.watermark import (
    human_watermark_issue_lines,
    human_watermark_latest_text,
)

__all__ = [
    "configure_matplotlib",
    "human_watermark_issue_lines",
    "human_watermark_latest_text",
    "render_quality_report_markdown",
]
