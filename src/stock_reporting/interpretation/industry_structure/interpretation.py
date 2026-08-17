"""行业结构业务研判与报告解读 Facade 模块。

聚合辅助规则与分档 (helpers) 与复杂报告段落评估器 (evaluators)，向外部提供统一接口。
"""

from __future__ import annotations

from stock_reporting.interpretation.industry_structure.evaluators import (
    evaluate_key_takeaways,
    evaluate_one_line_summary,
    evaluate_short_term_rhythm,
    evaluate_structure_radar,
    evaluate_theme_types,
)
from stock_reporting.interpretation.industry_structure.helpers import (
    evaluate_breadth_comment,
    get_fundamental_status_interpretation,
    get_fundamental_status_label,
    get_structure_health_level,
    has_fund_flow_pressure,
    has_weak_fundamental,
    is_fund_flow_confirmed,
    is_high_dividend,
)

__all__ = [
    "evaluate_breadth_comment",
    "evaluate_key_takeaways",
    "evaluate_one_line_summary",
    "evaluate_short_term_rhythm",
    "evaluate_structure_radar",
    "evaluate_theme_types",
    "get_fundamental_status_interpretation",
    "get_fundamental_status_label",
    "get_structure_health_level",
    "has_fund_flow_pressure",
    "has_weak_fundamental",
    "is_fund_flow_confirmed",
    "is_high_dividend",
]
