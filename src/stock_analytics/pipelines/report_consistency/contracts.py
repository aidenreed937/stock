"""报告一致性校验的产物契约与结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

ARTIFACT_FILES: dict[str, tuple[str, ...]] = {
    "market_temperature": (
        "manifest.json",
        "scores.json",
        "facts.parquet",
        "report.md",
        "report.json",
        "human_report.md",
        "quality_report.md",
        "quality_report.json",
    ),
    "industry_structure": (
        "manifest.json",
        "scores.json",
        "facts.parquet",
        "industry_panel.parquet",
        "report.md",
        "report.json",
        "human_report.md",
        "quality_report.md",
        "quality_report.json",
    ),
    "investor_brief": ("manifest.json", "brief_report.md", "brief_report.json"),
    "quant_brief": ("manifest.json", "brief_report.md", "brief_report.json"),
}

BANNED_UNSOURCED_PHRASES: tuple[str, ...] = (
    "政策刺激",
    "救市",
    "会议预期",
    "市场传闻",
    "国家队",
    "外资大幅流入",
    "全面牛市",
)


@dataclass(frozen=True, slots=True)
class Issue:
    severity: str
    check: str
    artifact: str
    as_of_date: str
    message: str


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    name: str
    root: Path
    run_dir: Path
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: str
    checked_dates: list[str]
    errors: list[Issue]
    warnings: list[Issue]


__all__ = [
    "ARTIFACT_FILES",
    "BANNED_UNSOURCED_PHRASES",
    "ArtifactBundle",
    "Issue",
    "ValidationResult",
]
