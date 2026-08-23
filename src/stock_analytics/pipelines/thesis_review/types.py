"""投资假设台账与跨周期复盘领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class InvestmentThesis:
    """初始投资假设数据契约。"""

    thesis_id: str
    symbol: str
    name: str
    created_date: str
    base_price: float
    initial_pe_ttm: float | None = None
    initial_dividend_yield: float | None = None
    expected_growth: float | None = None  # 预期年化净利增速 (%)
    expected_pe_anchor: float | None = None  # 预期合理估值中枢
    stop_loss_pct: float = -15.0  # 严格止损红线 (-15%)
    catalysts: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ThesisReviewAttribution:
    """跨周期走势与假设归因分析快照。"""

    current_price: float
    price_change_pct: float
    actual_growth: float | None = None
    growth_gap: float | None = None
    current_pe_ttm: float | None = None
    pe_change_pct: float | None = None
    is_stop_loss_triggered: bool = False
    is_value_trap: bool = False
    verdict: str = "持有观察"
    reflection_notes: list[str] = field(default_factory=list)
    action_guidance: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ThesisReviewResult:
    """投资假设验证与复盘全景结果。"""

    thesis: InvestmentThesis
    as_of_date: str
    days_elapsed: int
    attribution: ThesisReviewAttribution

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典结构。"""
        return asdict(self)
