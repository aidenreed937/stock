"""宏观风控多策略资金曲线对比图表与 Markdown 渲染门面代理。"""

from __future__ import annotations

from stock_reporting.templates.macro_strategy_comparison import (
    render_comparison_chart,
    render_comparison_markdown,
)

__all__ = ["render_comparison_chart", "render_comparison_markdown"]
