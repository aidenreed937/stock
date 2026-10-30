"""任务注册健康检查测试。"""

from __future__ import annotations

from stock_data.core import task_health


def test_task_health_checks_current_registry() -> None:
    report = task_health.run_task_health_checks()

    assert report.ok, task_health.format_task_health_report(report)
    assert report.checked_tasks > 0
    assert report.checked_bundles > 0
    assert report.checked_aliases > 0


def test_task_health_detects_broken_task_alias(monkeypatch) -> None:
    monkeypatch.setitem(task_health.TASK_ALIASES, ("tushare", "broken_alias"), "missing_task")

    report = task_health.run_task_health_checks(["tushare"])

    assert not report.ok
    assert any(issue.code == "unknown_task_reference" for issue in report.issues)


def test_task_health_detects_broken_bundle_member(monkeypatch) -> None:
    patched_bundles = dict(task_health.TASK_BUNDLE_TASKS["tushare"])
    patched_bundles["broken_bundle"] = ("missing_task",)
    monkeypatch.setitem(task_health.TASK_BUNDLE_TASKS, "tushare", patched_bundles)

    report = task_health.run_task_health_checks(["tushare"])

    assert not report.ok
    assert any(issue.code == "unknown_task_reference" for issue in report.issues)


def test_task_health_warns_when_technology_bundle_is_not_semiconductor_complete() -> None:
    report = task_health.run_task_health_checks(["industry"])

    assert report.ok
    issue = next(
        issue for issue in report.issues if issue.code == "partial_semiconductor_bundle_coverage"
    )
    assert "tsmc_advanced_packaging_revenue" in issue.message
    assert "tsmc_cowos_capacity_estimates" in issue.message
