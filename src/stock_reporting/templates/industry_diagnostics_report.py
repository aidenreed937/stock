"""中观产业与行业量化诊断研报渲染器。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.industry_diagnostics.logic import evaluate_industry_diagnostics

if TYPE_CHECKING:
    from stock_analytics.pipelines.industry_diagnostics.types import IndustryDiagnosticsResult


def render_industry_diagnostics_report(result: IndustryDiagnosticsResult | dict[str, Any]) -> str:
    """渲染中观产业深度诊断研报 Markdown。"""
    data = result.to_dict() if hasattr(result, "to_dict") else result
    eval_result = evaluate_industry_diagnostics(data)

    template_path = Path(__file__).parent / "industry_diagnostics.md.j2"
    if not template_path.exists():
        return f"模板文件未找到: {template_path}"

    template_content = template_path.read_text(encoding="utf-8")
    renderer = ReportRenderer()
    context = {"data": data, "eval_result": eval_result}
    return renderer.render_string(template_content, context)
