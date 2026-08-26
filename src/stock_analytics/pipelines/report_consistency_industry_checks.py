"""简报行业列表的来源与数值检查规则。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.report_consistency_hooks import ConsistencyCheckHooks
from stock_analytics.pipelines.report_consistency_utils import (
    _numbers_equal,
    _panel_by_name,
    _to_float,
)


class IndustryConsistencyChecksMixin(ConsistencyCheckHooks):
    def _check_brief_industry_snapshot(
        self,
        brief_json: dict[str, Any],
        industry_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        health = industry_scores.get("structure_health", {}).get("level")
        brief_health = (
            brief_json.get("industry_snapshot", {}).get("structure_health", {}).get("level")
        )
        if health != brief_health:
            message = f"简报结构健康度={brief_health!r}，行业健康度={health!r}"
            self._error("brief_industry_snapshot", "investor_brief", as_of_date, message)

    def _check_industry_lists(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        panel: pl.DataFrame,
        industry_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        panel_by_name = _panel_by_name(panel)
        self._check_candidate_rows(brief_json, brief_md, panel_by_name, as_of_date)
        self._check_risk_rows(brief_json, brief_md, panel_by_name, as_of_date)
        self._check_lagging_rows(brief_json, brief_md, panel_by_name, industry_scores, as_of_date)

    def _check_candidate_rows(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        panel_by_name: dict[str, dict[str, Any]],
        as_of_date: str,
    ) -> None:
        for row in brief_json.get("candidate_industries", []):
            source = self._check_brief_industry_row(row, brief_md, panel_by_name, as_of_date)
            if source is None:
                continue
            tags = str(row.get("tags") or source.get("tags") or "")
            crowding = row.get("crowding_temperature")
            if "拥挤风险" in tags or "景气承压" in tags or _to_float(crowding) >= 80:
                message = f"候选行业 {row.get('industry_name')} 含高拥挤或景气承压标签"
                self._error("brief_candidate_guard", "investor_brief", as_of_date, message)

    def _check_risk_rows(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        panel_by_name: dict[str, dict[str, Any]],
        as_of_date: str,
    ) -> None:
        for row in brief_json.get("risk_industries", []):
            source = self._check_brief_industry_row(row, brief_md, panel_by_name, as_of_date)
            if source is None:
                continue
            tags = str(row.get("tags") or source.get("tags") or "")
            crowding = _to_float(row.get("crowding_temperature"))
            if "拥挤风险" not in tags and crowding < 80:
                message = f"风险行业 {row.get('industry_name')} 缺少拥挤风险依据"
                self._error("brief_risk_guard", "investor_brief", as_of_date, message)

    def _check_lagging_rows(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        panel_by_name: dict[str, dict[str, Any]],
        industry_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        expected = {row.get("industry_name") for row in industry_scores.get("lagging_or_weak", [])}
        for row in brief_json.get("lagging_industries", []):
            source = self._check_brief_industry_row(row, brief_md, panel_by_name, as_of_date)
            if source is None:
                continue
            name = row.get("industry_name")
            if expected and name not in expected:
                self._error(
                    "brief_lagging_source",
                    "investor_brief",
                    as_of_date,
                    f"{name} 不在落后方向上游列表",
                )

    def _check_brief_industry_row(
        self,
        row: dict[str, Any],
        brief_md: str,
        panel_by_name: dict[str, dict[str, Any]],
        as_of_date: str,
        artifact: str = "investor_brief",
    ) -> dict[str, Any] | None:
        name = str(row.get("industry_name") or "")
        source = panel_by_name.get(name)
        self._require_text(brief_md, name, "brief_industry_name", artifact, as_of_date)
        if source is None:
            self._error(
                "brief_industry_source",
                artifact,
                as_of_date,
                f"{name} 不在行业面板",
            )
            return None
        for key in ("structure_score", "return_20d", "return_60d", "crowding_temperature"):
            if not _numbers_equal(row.get(key), source.get(key), precision=2):
                message = f"{name}.{key}={row.get(key)!r}，行业面板={source.get(key)!r}"
                self._error("brief_industry_value", artifact, as_of_date, message)
        return source
