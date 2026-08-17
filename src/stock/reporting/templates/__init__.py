"""Reporting 模板集。"""

from __future__ import annotations

from stock.reporting.templates.industry_structure import (
    build_report_json as build_industry_structure_report_json,
)
from stock.reporting.templates.industry_structure import (
    render_human_report_markdown as render_industry_structure_human_report_markdown,
)
from stock.reporting.templates.industry_structure import (
    render_report_markdown as render_industry_structure_markdown,
)
from stock.reporting.templates.investor_brief import (
    build_brief_json as build_investor_brief_json,
)
from stock.reporting.templates.investor_brief import (
    render_brief_markdown as render_investor_brief_markdown,
)
from stock.reporting.templates.market_temperature import (
    build_report_json as build_market_temperature_report_json,
)
from stock.reporting.templates.market_temperature import (
    render_human_report_markdown as render_market_temperature_human_report_markdown,
)
from stock.reporting.templates.market_temperature import (
    render_report_markdown as render_market_temperature_markdown,
)

__all__ = [
    "build_industry_structure_report_json",
    "build_investor_brief_json",
    "build_market_temperature_report_json",
    "render_industry_structure_human_report_markdown",
    "render_industry_structure_markdown",
    "render_investor_brief_markdown",
    "render_market_temperature_human_report_markdown",
    "render_market_temperature_markdown",
]
