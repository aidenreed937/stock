"""增量同步领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SyncTaskItem:
    """单个端点增量同步任务项。"""

    data_source: str
    endpoint: str
    dataset: str
    start_date: date
    end_date: date
    watermark: date | None
    status: str
    is_ready: bool
    reason: str = ""
    symbol: str = ""


@dataclass
class SyncExecutionResult:
    """增量同步执行统计结果。"""

    data_source: str
    endpoint: str
    start_date: date
    end_date: date
    records: int
    duration_s: float
    status: str
    error: str | None = None
    symbol: str = ""
