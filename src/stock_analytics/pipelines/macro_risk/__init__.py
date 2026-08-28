"""宏观系统性风险双轨制管线。"""

from stock_analytics.pipelines.macro_risk.artifacts import load_latest_risk_factors
from stock_analytics.pipelines.macro_risk.pipeline import MacroRiskPipeline

__all__ = ["MacroRiskPipeline", "load_latest_risk_factors"]
