"""报告文本与无来源叙事检查规则。"""

from __future__ import annotations

from typing import Any

from stock_analytics.pipelines.report_consistency_contracts import (
    BANNED_UNSOURCED_PHRASES,
    ArtifactBundle,
)
from stock_analytics.pipelines.report_consistency_hooks import ConsistencyCheckHooks
from stock_analytics.pipelines.report_consistency_utils import (
    _markdown_paths,
    _number_variants,
    _read_text,
)


class TextConsistencyChecksMixin(ConsistencyCheckHooks):
    def _check_forbidden_phrases(
        self,
        bundles: tuple[ArtifactBundle, ...],
        as_of_date: str,
    ) -> None:
        for bundle in bundles:
            for path in _markdown_paths(bundle):
                text = _read_text(path)
                for phrase in BANNED_UNSOURCED_PHRASES:
                    if phrase in text:
                        message = f"{path.name} 出现无本地事实支撑的叙事短语: {phrase}"
                        self._error("forbidden_phrase", bundle.name, as_of_date, message)

    def _require_text(
        self,
        text: str,
        expected: Any,
        check: str,
        artifact: str,
        as_of_date: str,
    ) -> None:
        if expected is None:
            return
        if str(expected) not in text:
            self._error(check, artifact, as_of_date, f"报告文本缺少 {expected!r}")

    def _require_number(
        self,
        text: str,
        expected: Any,
        check: str,
        artifact: str,
        as_of_date: str,
    ) -> None:
        if expected is None:
            return
        variants = _number_variants(expected)
        if variants and not any(value in text for value in variants):
            self._error(check, artifact, as_of_date, f"报告文本缺少数值 {sorted(variants)}")
