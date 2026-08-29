"""宏观风控多策略跨周期稳定性审计报告与图表渲染门面代理。"""

from __future__ import annotations

from stock_reporting.templates.macro_strategy_audit import (
    render_audit_markdown,
    render_stability_charts,
)

__all__ = ["render_audit_markdown", "render_stability_charts"]
