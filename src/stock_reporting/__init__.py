"""展现与视图层 (Presentation Layer)。

提供面向人工阅读的 Markdown、JSON 结构及终端 ASCII 卡片纯无状态渲染器。
"""

from __future__ import annotations

from stock_reporting.core.quality import render_quality_report_markdown
from stock_reporting.core.watermark import (
    human_watermark_issue_lines,
    human_watermark_latest_text,
)
from stock_reporting.templates.industry_structure import (
    build_report_json as build_industry_structure_report_json,
)
from stock_reporting.templates.industry_structure import (
    render_human_report_markdown as render_industry_structure_human_report_markdown,
)
from stock_reporting.templates.industry_structure import (
    render_report_markdown as render_industry_structure_markdown,
)
from stock_reporting.templates.investor_brief import (
    build_brief_json as build_investor_brief_json,
)
from stock_reporting.templates.investor_brief import (
    render_brief_markdown as render_investor_brief_markdown,
)
from stock_reporting.templates.market_aggregate import (
    build_quality_report as build_market_aggregate_quality_report,
)
from stock_reporting.templates.market_aggregate import (
    build_report_json as build_market_aggregate_report_json,
)
from stock_reporting.templates.market_aggregate import (
    render_human_report_markdown as render_market_aggregate_human_report_markdown,
)
from stock_reporting.templates.market_aggregate import (
    render_quality_report_markdown as render_market_aggregate_quality_report_markdown,
)
from stock_reporting.templates.market_aggregate import (
    render_report_markdown as render_market_aggregate_markdown,
)
from stock_reporting.templates.market_aggregate import (
    render_table_markdown as render_market_aggregate_table_markdown,
)
from stock_reporting.templates.market_temperature import (
    build_report_json as build_market_temperature_report_json,
)
from stock_reporting.templates.market_temperature import (
    render_human_report_markdown as render_market_temperature_human_report_markdown,
)
from stock_reporting.templates.market_temperature import (
    render_report_markdown as render_market_temperature_markdown,
)

__all__ = [
    "build_industry_structure_report_json",
    "build_investor_brief_json",
    "build_market_aggregate_quality_report",
    "build_market_aggregate_report_json",
    "build_market_temperature_report_json",
    "human_watermark_issue_lines",
    "human_watermark_latest_text",
    "render_industry_structure_human_report_markdown",
    "render_industry_structure_markdown",
    "render_investor_brief_markdown",
    "render_market_aggregate_human_report_markdown",
    "render_market_aggregate_markdown",
    "render_market_aggregate_quality_report_markdown",
    "render_market_aggregate_table_markdown",
    "render_market_temperature_human_report_markdown",
    "render_market_temperature_markdown",
    "render_quality_report_markdown",
]
