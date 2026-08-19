"""数据审计领域 (Domain)、时态周期 (Frequency) 与审计报告标准模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class AuditDomain(StrEnum):
    """数据审计业务领域分类。"""

    EQUITY = "equity"  # 个股微观领域 (K线、估值、复权、资金流、个股两融)
    INDUSTRY = "industry"  # 中观行业领域 (申万日行情、行业估值、成份图谱)
    INDEX = "index"  # 大盘指数领域 (大盘宽基K线、指数基本面估值)
    MACRO_LIQUIDITY = "macro_liquidity"  # 宏观流动性领域 (两融大盘、互联互通、中债收益率、Shibor)
    MACRO_ECON = "macro_econ"  # 宏观经济基本面 (GDP、CPI、PPI、PMI、社融、美联储指标)
    FUNDAMENTAL = "fundamental"  # 公司财务基本面 (利润表、资产负债表、现金流、财务指标)
    METADATA = "metadata"  # 字典与元数据领域 (股票列表、指数定义、行业分类)
    UNSUPPORTED = "unsupported"  # 未注册或尚未定义事实基准的数据集


class AuditFrequency(StrEnum):
    """数据时态周期分类。"""

    DAILY = "daily"  # 交易日日频
    MONTHLY = "monthly"  # 自然月频
    QUARTERLY = "quarterly"  # 自然/财报季频
    STATIC = "static"  # 静态快照 / 无固定周期


@dataclass(frozen=True)
class AuditReportResult:
    """标准化强类型审计对账结果模型。"""

    dataset: str
    data_source: str
    domain: AuditDomain
    frequency: AuditFrequency
    start_date: date
    end_date: date
    expected_count: int
    actual_count: int
    suspended_count: int = 0
    missing_count: int = 0
    integrity_rate: float = 100.0
    status: str = "PASSED"
    diagnostics: list[str] = field(default_factory=list)
    missing_samples: list[str] = field(default_factory=list)
    extra_samples: list[str] = field(default_factory=list)
    raw_curated_status: str = "PASSED"
    raw_count: int = 0
    curated_count: int = 0
    extra_metadata: dict[str, Any] = field(default_factory=dict)
