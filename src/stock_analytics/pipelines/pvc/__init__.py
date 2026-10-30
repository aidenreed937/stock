"""聚氯乙烯 (PVC / V) 垂直量化深度爆破管线包。

提供 PVC 多工艺成本曲线、期现基差与交割仓单蓄水池、海关出口、
四阶段库存时钟、上市公司估值反向时钟与三阶段量化交易门禁的全流程分析能力。
"""

from __future__ import annotations

from stock_analytics.pipelines.pvc.config import PVCConfig, load_pvc_config
from stock_analytics.pipelines.pvc.gates import (
    PVCGateRuleEvaluation,
    PVCGateStageResult,
    PVCTradingGatesSummary,
    evaluate_pvc_trading_gates,
)
from stock_analytics.pipelines.pvc.panorama import (
    build_pvc_monthly_panorama,
    classify_pvc_inventory_regime,
    detect_pvc_regime_episodes,
)
from stock_analytics.pipelines.pvc.pipeline import PVCPipeline, PVCRunResult
from stock_analytics.pipelines.pvc.report import render_pvc_markdown_report

__all__ = [
    "PVCConfig",
    "PVCGateRuleEvaluation",
    "PVCGateStageResult",
    "PVCPipeline",
    "PVCRunResult",
    "PVCTradingGatesSummary",
    "build_pvc_monthly_panorama",
    "classify_pvc_inventory_regime",
    "detect_pvc_regime_episodes",
    "evaluate_pvc_trading_gates",
    "load_pvc_config",
    "render_pvc_markdown_report",
]
