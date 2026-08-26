"""报告一致性校验器。"""

from __future__ import annotations

from pathlib import Path

from stock_analytics.pipelines.report_consistency_checks import ConsistencyChecksMixin
from stock_analytics.pipelines.report_consistency_contracts import (
    ARTIFACT_FILES,
    ArtifactBundle,
    Issue,
    ValidationResult,
)
from stock_analytics.pipelines.report_consistency_utils import (
    _in_range,
    _latest_run_dir,
    _read_json,
)


class ConsistencyValidator(ConsistencyChecksMixin):
    def __init__(self, analytics_root: Path) -> None:
        self.analytics_root = analytics_root
        self.errors: list[Issue] = []
        self.warnings: list[Issue] = []

    def validate_latest(self) -> ValidationResult:
        bundles = _load_bundles_for_latest(self)
        expected_date = _expected_latest_date(self, bundles)
        self._validate_date(expected_date, bundles)
        return self._result([expected_date])

    def validate_dates(
        self,
        dates: list[str],
        *,
        run_class: str | None = None,
    ) -> ValidationResult:
        for as_of_date in dates:
            bundles = _load_bundles_for_date(self, as_of_date, run_class=run_class)
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
                if artifact == "quant_brief":
                    self._warning(
                        "legacy_compatibility",
                        artifact,
                        expected_date,
                        "历史日期缺少 quant_brief，按 legacy compatibility mode 保留兼容告警",
                    )
                else:
                    self._error("required_files", artifact, expected_date, "缺少该日期产物目录")
                continue
            _check_required_files(self, bundle, expected_date)
            _check_manifest_date(self, bundle, expected_date)

        market = bundles.get("market_temperature")
        industry = bundles.get("industry_structure")
        brief = bundles.get("investor_brief")
        quant = bundles.get("quant_brief")
        if market is None or industry is None or brief is None:
            return

        self._check_market_report(market, expected_date)
        self._check_industry_report(industry, expected_date)
        self._check_brief_links(brief, market, industry, expected_date)
        self._check_brief_content(brief, market, industry, expected_date)
        if quant is not None:
            self._check_quant_links(quant, market, industry, expected_date)
            self._check_quant_content(quant, market, industry, expected_date)
        self._check_forbidden_phrases(
            tuple(bundle for bundle in (market, industry, brief, quant) if bundle is not None),
            expected_date,
        )

    def _error(self, check: str, artifact: str, as_of_date: str, message: str) -> None:
        self.errors.append(Issue("error", check, artifact, as_of_date, message))

    def _warning(self, check: str, artifact: str, as_of_date: str, message: str) -> None:
        self.warnings.append(Issue("warning", check, artifact, as_of_date, message))

    def _result(self, checked_dates: list[str]) -> ValidationResult:
        status = "passed" if not self.errors else "failed"
        return ValidationResult(status, checked_dates, self.errors, self.warnings)


def _load_bundles_for_latest(
    validator: ConsistencyValidator,
) -> dict[str, ArtifactBundle | None]:
    return {
        artifact: _load_bundle(validator, artifact, validator.analytics_root / artifact / "latest")
        for artifact in ARTIFACT_FILES
    }


def _load_bundles_for_date(
    validator: ConsistencyValidator,
    as_of_date: str,
    *,
    run_class: str | None = None,
) -> dict[str, ArtifactBundle | None]:
    return {
        artifact: _load_bundle(
            validator,
            artifact,
            _latest_run_dir(root, as_of_date, run_class=run_class),
        )
        for artifact in ARTIFACT_FILES
        for root in (validator.analytics_root / artifact,)
    }


def _load_bundle(
    validator: ConsistencyValidator,
    artifact: str,
    run_dir: Path | None,
) -> ArtifactBundle | None:
    if run_dir is None or not run_dir.exists():
        return None
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return ArtifactBundle(artifact, validator.analytics_root / artifact, run_dir, {})
    return ArtifactBundle(
        artifact,
        validator.analytics_root / artifact,
        run_dir,
        _read_json(manifest_path),
    )


def _expected_latest_date(
    validator: ConsistencyValidator,
    bundles: dict[str, ArtifactBundle | None],
) -> str:
    dates = {
        str(bundle.manifest.get("as_of_date"))
        for bundle in bundles.values()
        if bundle is not None and bundle.manifest.get("as_of_date")
    }
    if len(dates) == 1:
        return next(iter(dates))
    expected = sorted(dates)[-1] if dates else "latest"
    validator._error("latest_date", "all", expected, f"latest 基准日不一致: {sorted(dates)}")
    return expected


def _check_required_files(
    validator: ConsistencyValidator,
    bundle: ArtifactBundle,
    as_of_date: str,
) -> None:
    for filename in ARTIFACT_FILES[bundle.name]:
        if not (bundle.run_dir / filename).exists():
            validator._error("required_files", bundle.name, as_of_date, f"缺少文件 {filename}")


def _check_manifest_date(
    validator: ConsistencyValidator,
    bundle: ArtifactBundle,
    as_of_date: str,
) -> None:
    actual = bundle.manifest.get("as_of_date")
    if actual != as_of_date:
        message = f"manifest.as_of_date={actual!r}，期望 {as_of_date!r}"
        validator._error("manifest_date", bundle.name, as_of_date, message)
    run_id = bundle.manifest.get("run_id")
    if run_id and bundle.run_dir.name not in {"latest", run_id}:
        message = f"目录 run_id={bundle.run_dir.name!r} 与 manifest.run_id={run_id!r} 不一致"
        validator._error("manifest_run_id", bundle.name, as_of_date, message)
