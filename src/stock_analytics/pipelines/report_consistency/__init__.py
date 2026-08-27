"""报告一致性校验体系。"""

from __future__ import annotations

from stock_analytics.pipelines.report_consistency.contracts import (
    ARTIFACT_FILES,
    BANNED_UNSOURCED_PHRASES,
    ArtifactBundle,
    Issue,
    ValidationResult,
)
from stock_analytics.pipelines.report_consistency.utils import (
    _in_range,
    _is_finite,
    _latest_run_dir,
    _markdown_paths,
    _metric_value,
    _number_variants,
    _numbers_equal,
    _panel_by_name,
    _read_json,
    _read_text,
    _to_float,
    _watermark_dates,
)
from stock_analytics.pipelines.report_consistency.validator import ConsistencyValidator

__all__ = [
    "ARTIFACT_FILES",
    "BANNED_UNSOURCED_PHRASES",
    "ArtifactBundle",
    "ConsistencyValidator",
    "Issue",
    "ValidationResult",
    "_in_range",
    "_is_finite",
    "_latest_run_dir",
    "_markdown_paths",
    "_metric_value",
    "_number_variants",
    "_numbers_equal",
    "_panel_by_name",
    "_read_json",
    "_read_text",
    "_to_float",
    "_watermark_dates",
]
