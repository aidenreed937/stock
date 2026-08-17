"""市场温度计业务研判与报告解读 Facade 模块。

聚合分档规则 (bands) 与复杂报告段落评估器 (evaluators)，向外部提供统一接口。
"""

from __future__ import annotations

from stock_reporting.interpretation.market_temperature.bands import (
    _DIMENSION_FOCUS,
    _DIMENSION_LABELS,
    _DIMENSION_TIMELINESS,
    _METRIC_LABELS,
    get_cross_period_comment,
    get_dimension_comment,
    get_pressure_band,
    get_pressure_comment,
    get_systemic_risk_level,
    get_temperature_band,
)
from stock_reporting.interpretation.market_temperature.evaluators import (
    evaluate_external_pressure_section,
    evaluate_follow_ups,
    evaluate_interpretation_priority_rows,
    evaluate_key_divergences,
    evaluate_one_line_summary,
    evaluate_reading_brief,
    evaluate_systemic_risk_section,
)

__all__ = [
    "_DIMENSION_FOCUS",
    "_DIMENSION_LABELS",
    "_DIMENSION_TIMELINESS",
    "_METRIC_LABELS",
    "evaluate_external_pressure_section",
    "evaluate_follow_ups",
    "evaluate_interpretation_priority_rows",
    "evaluate_key_divergences",
    "evaluate_one_line_summary",
    "evaluate_reading_brief",
    "evaluate_systemic_risk_section",
    "get_cross_period_comment",
    "get_dimension_comment",
    "get_pressure_band",
    "get_pressure_comment",
    "get_systemic_risk_level",
    "get_temperature_band",
]
