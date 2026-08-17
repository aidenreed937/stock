"""普通投资者简报解读与配置模块。"""

from stock_reporting.interpretation.investor_brief.config import (
    DEFAULT_CONFIG_PATH,
    InvestorBriefConfig,
    load_investor_brief_config,
)
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_candidate_industries,
    evaluate_lagging_industries,
    evaluate_participation_decision,
    evaluate_reading_notes,
    evaluate_risk_industries,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "InvestorBriefConfig",
    "evaluate_candidate_industries",
    "evaluate_lagging_industries",
    "evaluate_participation_decision",
    "evaluate_reading_notes",
    "evaluate_risk_industries",
    "load_investor_brief_config",
]
