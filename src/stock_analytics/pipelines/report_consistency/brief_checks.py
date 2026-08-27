"""投资者简报与量化简报检查规则。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.report_consistency.contracts import (
    ArtifactBundle,
)
from stock_analytics.pipelines.report_consistency.hooks import ConsistencyCheckHooks
from stock_analytics.pipelines.report_consistency.utils import (
    _metric_value,
    _numbers_equal,
    _panel_by_name,
    _read_json,
    _read_text,
    _watermark_dates,
)


class BriefConsistencyChecksMixin(ConsistencyCheckHooks):
    def _check_brief_links(
        self,
        brief: ArtifactBundle,
        market: ArtifactBundle,
        industry: ArtifactBundle,
        as_of_date: str,
    ) -> None:
        inputs = brief.manifest.get("inputs", {})
        self._check_input_link(inputs, "market_temperature", market, as_of_date)
        self._check_input_link(inputs, "industry_structure", industry, as_of_date)

    def _check_quant_links(
        self,
        quant: ArtifactBundle,
        market: ArtifactBundle,
        industry: ArtifactBundle,
        as_of_date: str,
    ) -> None:
        inputs = quant.manifest.get("inputs", {})
        self._check_input_link(inputs, "market_temperature", market, as_of_date, "quant_brief")
        self._check_input_link(inputs, "industry_structure", industry, as_of_date, "quant_brief")

    def _check_input_link(
        self,
        inputs: dict[str, Any],
        key: str,
        upstream: ArtifactBundle,
        as_of_date: str,
        artifact: str = "investor_brief",
    ) -> None:
        payload = inputs.get(key, {})
        if payload.get("as_of_date") != as_of_date:
            self._error("brief_input_date", artifact, as_of_date, f"{key} 日期不一致")
        run_id = payload.get("run_id")
        upstream_run_id = upstream.manifest.get("run_id")
        if run_id != upstream_run_id:
            message = f"{key} run_id={run_id!r}，上游 run_id={upstream_run_id!r}"
            self._error("brief_input_run", artifact, as_of_date, message)
        if run_id and not (upstream.root / "runs" / f"as_of={as_of_date}" / str(run_id)).exists():
            self._error("brief_input_exists", artifact, as_of_date, f"{key} run 不存在")

    def _check_brief_content(
        self,
        brief: ArtifactBundle,
        market: ArtifactBundle,
        industry: ArtifactBundle,
        as_of_date: str,
    ) -> None:
        brief_json = _read_json(brief.run_dir / "brief_report.json")
        brief_md = _read_text(brief.run_dir / "brief_report.md")
        market_scores = _read_json(market.run_dir / "scores.json")
        industry_scores = _read_json(industry.run_dir / "scores.json")
        market_facts_path = market.run_dir / "facts.parquet"
        market_facts = (
            pl.read_parquet(market_facts_path) if market_facts_path.exists() else pl.DataFrame()
        )
        panel = pl.read_parquet(industry.run_dir / "industry_panel.parquet")

        self._check_brief_market_snapshot(brief_json, market_scores, as_of_date)
        self._check_brief_watermarks(brief_json, brief_md, market_facts, as_of_date)
        self._check_brief_industry_snapshot(brief_json, industry_scores, as_of_date)
        self._require_text(brief_md, as_of_date, "brief_date", brief.name, as_of_date)
        self._check_industry_lists(brief_json, brief_md, panel, industry_scores, as_of_date)

    def _check_quant_content(
        self,
        quant: ArtifactBundle,
        market: ArtifactBundle,
        industry: ArtifactBundle,
        as_of_date: str,
    ) -> None:
        quant_json = _read_json(quant.run_dir / "brief_report.json")
        quant_md = _read_text(quant.run_dir / "brief_report.md")
        market_scores = _read_json(market.run_dir / "scores.json")
        facts_path = market.run_dir / "facts.parquet"
        facts = pl.read_parquet(facts_path) if facts_path.exists() else pl.DataFrame()
        panel = pl.read_parquet(industry.run_dir / "industry_panel.parquet")

        self._require_text(quant_md, as_of_date, "quant_date", quant.name, as_of_date)
        composite = market_scores.get("composite", {}).get("temperature")
        macro = quant_json.get("macro", {})
        if not _numbers_equal(composite, macro.get("temperature")):
            self._error(
                "quant_macro_temperature",
                quant.name,
                as_of_date,
                f"量化简报综合温度={macro.get('temperature')!r}，市场温度={composite!r}",
            )
        risk = market_scores.get("systemic_risk", {}).get("level")
        if risk != macro.get("risk_level"):
            self._error(
                "quant_macro_risk",
                quant.name,
                as_of_date,
                f"量化简报风险等级={macro.get('risk_level')!r}，市场风险等级={risk!r}",
            )

        expected_delta = market_scores.get("drivers", {}).get("composite_delta")
        actual_delta = quant_json.get("nature", {}).get("composite_delta")
        if not _numbers_equal(expected_delta, actual_delta):
            self._error(
                "quant_nature_delta",
                quant.name,
                as_of_date,
                f"量化简报综合温度变化={actual_delta!r}，市场驱动变化={expected_delta!r}",
            )
        top5 = _metric_value(facts, "amount_top_5pct_share")
        actual_top5 = quant_json.get("veto", {}).get("top5pct", {}).get("value")
        if not _numbers_equal(top5, actual_top5):
            self._error(
                "quant_top5_value",
                quant.name,
                as_of_date,
                f"量化简报 Top5%={actual_top5!r}，市场事实={top5!r}",
            )
        self._check_quant_sector_rows(quant_json, quant_md, panel, as_of_date)

    def _check_quant_sector_rows(
        self,
        quant_json: dict[str, Any],
        quant_md: str,
        panel: pl.DataFrame,
        as_of_date: str,
    ) -> None:
        panel_by_name = _panel_by_name(panel)
        sector = quant_json.get("sector", {})
        for group in ("priority", "avoid", "lagging"):
            rows = sector.get(group, []) if isinstance(sector, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    self._check_brief_industry_row(
                        row,
                        quant_md,
                        panel_by_name,
                        as_of_date,
                        artifact="quant_brief",
                    )

    def _check_brief_market_snapshot(
        self,
        brief_json: dict[str, Any],
        market_scores: dict[str, Any],
        as_of_date: str,
    ) -> None:
        composite = market_scores.get("composite", {}).get("temperature")
        brief_composite = brief_json.get("market_snapshot", {}).get("composite_temperature")
        if not _numbers_equal(composite, brief_composite):
            message = f"简报综合温度={brief_composite!r}，市场温度={composite!r}"
            self._error("brief_market_snapshot", "investor_brief", as_of_date, message)
        risk = market_scores.get("systemic_risk", {}).get("level")
        brief_risk = brief_json.get("participation", {}).get("risk_level")
        if risk != brief_risk:
            message = f"简报风险等级={brief_risk!r}，市场风险等级={risk!r}"
            self._error("brief_market_snapshot", "investor_brief", as_of_date, message)
        external_risk = market_scores.get("external_risk")
        brief_external_risk = brief_json.get("market_snapshot", {}).get("external_risk")
        if isinstance(external_risk, dict) and external_risk != brief_external_risk:
            message = "简报外盘风险状态与市场温度外盘风险状态不一致"
            self._error("brief_market_snapshot", "investor_brief", as_of_date, message)

    def _check_brief_watermarks(
        self,
        brief_json: dict[str, Any],
        brief_md: str,
        market_facts: pl.DataFrame,
        as_of_date: str,
    ) -> None:
        expected = _watermark_dates(market_facts)
        tracked = {"stock_daily_bar", "margin", "moneyflow"} & expected.keys()
        if not tracked:
            return

        actual = brief_json.get("data_watermarks")
        actual = actual if isinstance(actual, dict) else {}
        for dataset in sorted(tracked):
            expected_date = expected[dataset]
            if actual.get(dataset) != expected_date:
                message = f"简报 {dataset} 日期={actual.get(dataset)!r}，市场事实={expected_date!r}"
                self._error("brief_data_watermark", "investor_brief", as_of_date, message)
            if expected_date not in brief_md:
                self._error(
                    "brief_data_watermark_display",
                    "investor_brief",
                    as_of_date,
                    f"简报文本未展示 {dataset} 日期 {expected_date}",
                )


__all__ = ["BriefConsistencyChecksMixin"]
