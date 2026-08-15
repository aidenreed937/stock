"""市场指标标准输出模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from datetime import date

    from stock.analytics.metrics.spec import DiagnosticLevel


type MetricFrame = pl.DataFrame


@dataclass(frozen=True, slots=True)
class MetricDiagnostic:
    """指标计算诊断信息。"""

    metric_id: str
    level: DiagnosticLevel
    message: str


@dataclass(frozen=True, slots=True)
class MetricResult:
    """单个指标计算结果。"""

    metric_id: str
    trade_date: date | None
    frame: MetricFrame
    diagnostics: tuple[MetricDiagnostic, ...] = ()
