"""半导体深研线：回测/IC 验证研究子包。

承接 `stock_analytics.pipelines.semiconductor`（数据腿）的分层消费：
- IC 验证（整体/年度/当前截面 Spearman IC）；
- 单行业事件状态机回测（buy_hold / scissors_neg / inv_high / scissors_inv）；
- 落盘 CSV + Markdown 报告到 `data/strategy/semiconductor/`。

本层（stock_strategy）是**验证层**：消费上游特征（feature / 候选因子），
通过 IC / 回测 / 敏感性扫描验证其是否为**有效因子（factor）**，不产生新特征。
"""

from __future__ import annotations

from stock_strategy.industry.semiconductor.backtest import (
    position_weight,
    run_backtest,
)
from stock_strategy.industry.semiconductor.config import (
    DEFAULT_CONFIG_PATH,
    DefenseConfig,
    SemiconductorResearchConfig,
    load_semiconductor_research_config,
)
from stock_strategy.industry.semiconductor.data import load_semiconductor_panel
from stock_strategy.industry.semiconductor.ic import (
    attach_f60,
    current_cross_section,
    overall_ic,
    spearman_ic,
    yearly_ic,
)
from stock_strategy.industry.semiconductor.metrics import compute_metrics
from stock_strategy.industry.semiconductor.pipeline import (
    SemiconductorResearchResult,
    run_semiconductor_research,
)
from stock_strategy.industry.semiconductor.sensitivity import (
    sweep_doi_threshold,
    sweep_drawdown_weight,
)
from stock_strategy.industry.semiconductor.validation import (
    ValidationResult,
    run_validation,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DefenseConfig",
    "SemiconductorResearchConfig",
    "SemiconductorResearchResult",
    "ValidationResult",
    "attach_f60",
    "compute_metrics",
    "current_cross_section",
    "load_semiconductor_panel",
    "load_semiconductor_research_config",
    "overall_ic",
    "position_weight",
    "run_backtest",
    "run_semiconductor_research",
    "run_validation",
    "spearman_ic",
    "sweep_doi_threshold",
    "sweep_drawdown_weight",
    "yearly_ic",
]
