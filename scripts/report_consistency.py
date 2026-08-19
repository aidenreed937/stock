"""校验市场温度、行业结构和投资者简报的一致性。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

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


class ConsistencyValidator:
    def __init__(self, analytics_root: Path) -> None:
        self.analytics_root = analytics_root
        self.errors: list[Issue] = []
        self.warnings: list[Issue] = []

    def validate_latest(self) -> ValidationResult:
        bundles = self._load_bundles_for_latest()
        expected_date = self._expected_latest_date(bundles)
        self._validate_date(expected_date, bundles)
        return self._result([expected_date])

    def validate_dates(self, dates: list[str]) -> ValidationResult:
        for as_of_date in dates:
            bundles = self._load_bundles_for_date(as_of_date)
            self._validate_date(as_of_date, bundles)
        return self._result(dates)

    def available_dates(self, start: str | None, end: str | None) -> list[str]:
        dates: set[str] = set()
        for artifact in ARTIFACT_FILES:
            root = self.analytics_root / artifact / "runs"
            for path in root.glob("as_of=*"):
                if path.is_dir():
                    dates.add(path.name.split("=", maxsplit=1)[1])
        return [value for value in sorted(dates) if _in_range(value, start, end)]

    def _validate_date(
        self,
        expected_date: str,
        bundles: dict[str, ArtifactBundle | None],
    ) -> None:
        for artifact, bundle in bundles.items():
            if bundle is None:
                self._error("required_files", artifact, expected_date, "缺少该日期产物目录")
                continue
            self._check_required_files(bundle, expected_date)
            self._check_manifest_date(bundle, expected_date)

        market = bundles.get("market_temperature")
        industry = bundles.get("industry_structure")
        brief = bundles.get("investor_brief")
        if market is None or industry is None or brief is None:
            return

        self._check_market_report(market, expected_date)
        self._check_industry_report(industry, expected_date)
        self._check_brief_links(brief, market, industry, expected_date)
        self._check_brief_content(brief, market, industry, expected_date)
        self._check_forbidden_phrases((market, industry, brief), expected_date)

    def _load_bundles_for_latest(self) -> dict[str, ArtifactBundle | None]:
        return {
            artifact: self._load_bundle(artifact, self.analytics_root / artifact / "latest")
            for artifact in ARTIFACT_FILES
        }

    def _load_bundles_for_date(self, as_of_date: str) -> dict[str, ArtifactBundle | None]:
        return {
            artifact: self._load_bundle(artifact, _latest_run_dir(root, as_of_date))
            for artifact in ARTIFACT_FILES
            for root in (self.analytics_root / artifact,)
        }

    def _load_bundle(self, artifact: str, run_dir: Path | None) -> ArtifactBundle | None:
        if run_dir is None or not run_dir.exists():
            return None
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            return ArtifactBundle(artifact, self.analytics_root / artifact, run_dir, {})
        return ArtifactBundle(
            artifact,
            self.analytics_root / artifact,
            run_dir,
            _read_json(manifest_path),
        )

    def _expected_latest_date(self, bundles: dict[str, ArtifactBundle | None]) -> str:
        dates = {
            str(bundle.manifest.get("as_of_date"))
            for bundle in bundles.values()
            if bundle is not None and bundle.manifest.get("as_of_date")
        }
        if len(dates) == 1:
            return next(iter(dates))
        expected = sorted(dates)[-1] if dates else "latest"
        self._error("latest_date", "all", expected, f"latest 基准日不一致: {sorted(dates)}")
        return expected

    def _check_required_files(self, bundle: ArtifactBundle, as_of_date: str) -> None:
        for filename in ARTIFACT_FILES[bundle.name]:
            if not (bundle.run_dir / filename).exists():
                self._error("required_files", bundle.name, as_of_date, f"缺少文件 {filename}")

    def _check_manifest_date(self, bundle: ArtifactBundle, as_of_date: str) -> None:
        actual = bundle.manifest.get("as_of_date")
        if actual != as_of_date:
            message = f"manifest.as_of_date={actual!r}，期望 {as_of_date!r}"
            self._error("manifest_date", bundle.name, as_of_date, message)
        run_id = bundle.manifest.get("run_id")
        if run_id and bundle.run_dir.name not in {"latest", run_id}:
            message = f"目录 run_id={bundle.run_dir.name!r} 与 manifest.run_id={run_id!r} 不一致"
            self._error("manifest_run_id", bundle.name, as_of_date, message)

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

    def _check_input_link(
        self,
        inputs: dict[str, Any],
        key: str,
        upstream: ArtifactBundle,
        as_of_date: str,
    ) -> None:
        payload = inputs.get(key, {})
        if payload.get("as_of_date") != as_of_date:
            self._error("brief_input_date", "investor_brief", as_of_date, f"{key} 日期不一致")
        run_id = payload.get("run_id")
        upstream_run_id = upstream.manifest.get("run_id")
        if run_id != upstream_run_id:
            message = f"{key} run_id={run_id!r}，上游 run_id={upstream_run_id!r}"
            self._error("brief_input_run", "investor_brief", as_of_date, message)
        if run_id and not (upstream.root / "runs" / f"as_of={as_of_date}" / str(run_id)).exists():
            self._error("brief_input_exists", "investor_brief", as_of_date, f"{key} run 不存在")

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
    ) -> dict[str, Any] | None:
        name = str(row.get("industry_name") or "")
        source = panel_by_name.get(name)
        self._require_text(brief_md, name, "brief_industry_name", "investor_brief", as_of_date)
        if source is None:
            self._error(
                "brief_industry_source",
                "investor_brief",
                as_of_date,
                f"{name} 不在行业面板",
            )
            return None
        for key in ("structure_score", "return_20d", "return_60d", "crowding_temperature"):
            if not _numbers_equal(row.get(key), source.get(key), precision=2):
                message = f"{name}.{key}={row.get(key)!r}，行业面板={source.get(key)!r}"
                self._error("brief_industry_value", "investor_brief", as_of_date, message)
        return source

    def _check_forbidden_phrases(
        self,
        bundles: tuple[ArtifactBundle, ArtifactBundle, ArtifactBundle],
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

    def _error(self, check: str, artifact: str, as_of_date: str, message: str) -> None:
        self.errors.append(Issue("error", check, artifact, as_of_date, message))

    def _result(self, checked_dates: list[str]) -> ValidationResult:
        status = "passed" if not self.errors else "failed"
        return ValidationResult(status, checked_dates, self.errors, self.warnings)


def _latest_run_dir(root: Path, as_of_date: str) -> Path | None:
    run_root = root / "runs" / f"as_of={as_of_date}"
    if not run_root.exists():
        return None
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    return run_dirs[-1] if run_dirs else None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _markdown_paths(bundle: ArtifactBundle) -> tuple[Path, ...]:
    names = {
        "market_temperature": ("report.md", "human_report.md", "quality_report.md"),
        "industry_structure": ("report.md", "human_report.md", "quality_report.md"),
        "investor_brief": ("brief_report.md",),
    }
    return tuple(bundle.run_dir / name for name in names[bundle.name])


def _number_variants(value: Any) -> set[str]:
    number = _to_float(value)
    if not _is_finite(number):
        return set()
    return {str(value), f"{number:.2f}", f"{number:.1f}", f"{number:.0f}"}


def _numbers_equal(left: Any, right: Any, *, precision: int = 2) -> bool:
    left_number = _to_float(left)
    right_number = _to_float(right)
    if not _is_finite(left_number) or not _is_finite(right_number):
        return left == right
    return round(left_number, precision) == round(right_number, precision)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _is_finite(value: float) -> bool:
    return math.isfinite(value)


def _panel_by_name(panel: pl.DataFrame) -> dict[str, dict[str, Any]]:
    if "industry_name" not in panel.columns:
        return {}
    return {str(row["industry_name"]): row for row in panel.to_dicts()}


def _watermark_dates(facts: pl.DataFrame) -> dict[str, str]:
    if facts.is_empty():
        return {}
    required = {"category", "dataset", "metric_id", "status", "value_text"}
    if not required.issubset(facts.columns):
        return {}
    rows = (
        facts.filter(
            (facts["category"] == "data_watermark")
            & (facts["metric_id"] == "latest_trade_date")
            & (facts["status"] == "ok")
        )
        .select(["dataset", "value_text"])
        .to_dicts()
    )
    return {
        str(row["dataset"]): str(row["value_text"])
        for row in rows
        if row.get("dataset") and row.get("value_text")
    }


def _in_range(value: str, start: str | None, end: str | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验分析报告与上游事实/规则的一致性")
    parser.add_argument("--analytics-root", default="data/analytics", help="分析产物根目录")
    parser.add_argument("--date", help="只校验指定基准日 YYYY-MM-DD")
    parser.add_argument("--start", help="批量校验起始基准日 YYYY-MM-DD")
    parser.add_argument("--end", help="批量校验结束基准日 YYYY-MM-DD")
    parser.add_argument("--output", help="可选 JSON 校验报告输出路径")
    return parser.parse_args(argv)


def _target_dates(args: argparse.Namespace, validator: ConsistencyValidator) -> list[str] | None:
    if args.date:
        return [date.fromisoformat(args.date).isoformat()]
    if args.start or args.end:
        start = date.fromisoformat(args.start).isoformat() if args.start else None
        end = date.fromisoformat(args.end).isoformat() if args.end else None
        return validator.available_dates(start, end)
    return None


def _print_result(result: ValidationResult) -> None:
    print(f"report_consistency: {result.status}")
    print(f"checked_dates: {len(result.checked_dates)}")
    print(f"errors: {len(result.errors)}")
    print(f"warnings: {len(result.warnings)}")
    for issue in result.errors[:50]:
        print(f"[ERROR] {issue.as_of_date} {issue.artifact} {issue.check}: {issue.message}")
    for issue in result.warnings[:50]:
        print(f"[WARN] {issue.as_of_date} {issue.artifact} {issue.check}: {issue.message}")


def _write_output(result: ValidationResult, output: str | None) -> None:
    if not output:
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": result.status,
        "checked_dates": result.checked_dates,
        "errors": [asdict(issue) for issue in result.errors],
        "warnings": [asdict(issue) for issue in result.warnings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    validator = ConsistencyValidator(Path(args.analytics_root))
    dates = _target_dates(args, validator)
    result = validator.validate_dates(dates) if dates is not None else validator.validate_latest()
    _print_result(result)
    _write_output(result, args.output)
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
