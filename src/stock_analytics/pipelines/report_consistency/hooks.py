"""报告一致性规则组之间共享的校验钩子类型。"""

from __future__ import annotations

from typing import Any

import polars as pl


class ConsistencyCheckHooks:
    def _error(self, check: str, artifact: str, as_of_date: str, message: str) -> None:
        raise NotImplementedError

    def _warning(self, check: str, artifact: str, as_of_date: str, message: str) -> None:
        raise NotImplementedError

    def _require_text(
        self,
        text: str,
        expected: Any,
        check: str,
        artifact: str,
        as_of_date: str,
    ) -> None:
        raise NotImplementedError

    def _require_number(
        self,
        text: str,
        expected: Any,
        check: str,
        artifact: str,
        as_of_date: str,
    ) -> None:
        raise NotImplementedError

    def _check_industry_lists(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        panel: pl.DataFrame,
        industry_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        raise NotImplementedError

    def _check_brief_industry_snapshot(
        self,
        brief_json: dict[str, Any],
        industry_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        raise NotImplementedError

    def _check_brief_industry_row(
        self,
        row: dict[str, Any],
        brief_md: str,
        panel_by_name: dict[str, dict[str, Any]],
        as_of_date: str,
        artifact: str = "investor_brief",
    ) -> dict[str, Any] | None:
        raise NotImplementedError


__all__ = ["ConsistencyCheckHooks"]
