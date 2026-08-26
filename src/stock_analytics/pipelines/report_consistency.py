"""报告一致性校验兼容门面。

具体契约、读取工具和校验规则分别位于同目录的专用模块；保留本入口以兼容现有调用方。
"""

from __future__ import annotations

from stock_analytics.pipelines.report_consistency_contracts import (
    ARTIFACT_FILES,
    BANNED_UNSOURCED_PHRASES,
    ArtifactBundle,
    Issue,
    ValidationResult,
)
from stock_analytics.pipelines.report_consistency_utils import (  # noqa: F401
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
from stock_analytics.pipelines.report_consistency_validator import ConsistencyValidator

__all__ = [
    "ARTIFACT_FILES",
    "BANNED_UNSOURCED_PHRASES",
    "ArtifactBundle",
    "ConsistencyValidator",
    "Issue",
    "ValidationResult",
]
