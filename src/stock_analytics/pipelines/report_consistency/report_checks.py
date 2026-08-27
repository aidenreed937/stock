"""市场温度与行业结构报告检查规则。"""

from __future__ import annotations

from stock_analytics.pipelines.report_consistency.contracts import (
    ArtifactBundle,
)
from stock_analytics.pipelines.report_consistency.hooks import ConsistencyCheckHooks
from stock_analytics.pipelines.report_consistency.utils import (
    _read_json,
    _read_text,
)


class ReportConsistencyChecksMixin(ConsistencyCheckHooks):
    def _check_market_report(self, bundle: ArtifactBundle, as_of_date: str) -> None:
        scores = _read_json(bundle.run_dir / "scores.json")
        report = _read_text(bundle.run_dir / "report.md")
        human = _read_text(bundle.run_dir / "human_report.md")
        composite = scores.get("composite", {}).get("temperature")
        risk_level = scores.get("systemic_risk", {}).get("level")

        self._require_text(report, as_of_date, "market_report", bundle.name, as_of_date)
        self._require_text(human, as_of_date, "market_human", bundle.name, as_of_date)
        self._require_number(report + human, composite, "composite", bundle.name, as_of_date)
        self._require_text(report + human, risk_level, "risk_level", bundle.name, as_of_date)

        external_risk = scores.get("external_risk")
        if isinstance(external_risk, dict):
            self._require_number(
                report + human,
                external_risk.get("background_pressure"),
                "external_background_pressure",
                bundle.name,
                as_of_date,
            )
            self._require_number(
                report + human,
                external_risk.get("environment_temperature"),
                "external_environment_temperature",
                bundle.name,
                as_of_date,
            )
            self._require_text(
                report + human,
                external_risk.get("shock_status"),
                "external_shock_status",
                bundle.name,
                as_of_date,
            )
            self._require_text(
                report + human,
                external_risk.get("transmission_status"),
                "external_transmission_status",
                bundle.name,
                as_of_date,
            )
            self._require_text(
                report + human,
                external_risk.get("message"),
                "external_risk_message",
                bundle.name,
                as_of_date,
            )

        for dimension in scores.get("dimensions", []):
            self._require_text(
                report + human,
                dimension.get("name"),
                "dimension",
                bundle.name,
                as_of_date,
            )
            self._require_number(
                report + human,
                dimension.get("temperature"),
                "dimension_temperature",
                bundle.name,
                as_of_date,
            )

    def _check_industry_report(self, bundle: ArtifactBundle, as_of_date: str) -> None:
        scores = _read_json(bundle.run_dir / "scores.json")
        report = _read_text(bundle.run_dir / "report.md")
        human = _read_text(bundle.run_dir / "human_report.md")
        health = scores.get("structure_health", {}).get("level")

        self._require_text(report, as_of_date, "industry_report", bundle.name, as_of_date)
        self._require_text(human, as_of_date, "industry_human", bundle.name, as_of_date)
        self._require_text(report + human, health, "structure_health", bundle.name, as_of_date)
        for row in scores.get("top_structure", [])[:10]:
            self._require_text(
                report + human,
                row.get("industry_name"),
                "top_structure",
                bundle.name,
                as_of_date,
            )
            self._require_number(
                report + human,
                row.get("structure_score") or row.get("score"),
                "top_structure_score",
                bundle.name,
                as_of_date,
            )


__all__ = ["ReportConsistencyChecksMixin"]
