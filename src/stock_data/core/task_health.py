"""任务注册健康检查。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from stock_data.core.provider_registry import PROVIDER_REGISTRY_IMPORTS, provider_registry
from stock_data.core.task_aliases import DISABLED_TASKS, EXPLICIT_ONLY_TASKS, TASK_ALIASES
from stock_data.core.task_bundle_aliases import TASK_BUNDLE_ALIASES
from stock_data.core.task_bundle_specs import TASK_BUNDLE_TASKS
from stock_data.core.task_bundles import resolve_bundle_or_alias
from stock_data.core.task_catalog import list_available_tasks
from stock_data.core.task_manual_specs import CUSTOM_TASKS
from stock_data.core.task_resolution import resolve_task
from stock_data.core.task_types import TaskSpec
from stock_data.core.tushare_internal_apis import is_tushare_internal_api

TaskHealthSeverity = Literal["error", "warning"]

_SEVERITY_ORDER = {"error": 0, "warning": 1}
_VALID_FETCH_MODES = frozenset({"per_day", "per_symbol", "per_period"})
_VALID_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "event", "static"})
_VALID_SYNC_POLICIES = frozenset({"incremental", "manual_snapshot"})


@dataclass(frozen=True)
class TaskHealthIssue:
    """任务注册自检发现的问题。"""

    severity: TaskHealthSeverity
    code: str
    provider: str
    subject: str
    message: str


@dataclass(frozen=True)
class TaskHealthReport:
    """任务注册自检结果。"""

    checked_providers: tuple[str, ...]
    checked_tasks: int
    checked_bundles: int
    checked_aliases: int
    issues: tuple[TaskHealthIssue, ...]

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_providers": self.checked_providers,
            "checked_tasks": self.checked_tasks,
            "checked_bundles": self.checked_bundles,
            "checked_aliases": self.checked_aliases,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [asdict(issue) for issue in self.issues],
        }


def known_task_providers() -> tuple[str, ...]:
    """返回任务注册体系中出现过的 Provider。"""
    providers = set(PROVIDER_REGISTRY_IMPORTS)
    providers.update(TASK_BUNDLE_TASKS)
    providers.update(provider for provider, _ in TASK_BUNDLE_ALIASES)
    providers.update(provider for provider, _ in TASK_ALIASES)
    providers.update(provider for provider, _ in CUSTOM_TASKS)
    return tuple(sorted(providers))


def run_task_health_checks(providers: Iterable[str] | None = None) -> TaskHealthReport:
    """执行只读任务注册健康检查。"""
    selected = tuple(
        dict.fromkeys(provider.lower() for provider in providers or known_task_providers())
    )
    issues: list[TaskHealthIssue] = []
    checked_tasks: set[tuple[str, str]] = set()
    checked_bundles = 0
    checked_aliases = 0

    for provider_name in selected:
        if provider_name not in known_task_providers():
            issues.append(
                _issue(
                    "error",
                    "unknown_provider",
                    provider_name,
                    provider_name,
                    "Provider 未出现在任务注册、任务包或别名配置中。",
                )
            )
            continue

        registry_names = _load_registry_names(provider_name, issues)
        registered_names = _registered_task_names(provider_name, registry_names)

        checked_aliases += _check_task_aliases(provider_name, registered_names, issues)
        checked_bundles += _check_task_bundles(provider_name, registered_names, issues)
        checked_bundles += _check_task_bundle_aliases(provider_name, registered_names, issues)
        _check_industry_bundle_scope(provider_name, issues)
        checked_tasks.update(_check_public_catalog(provider_name, registered_names, issues))
        checked_tasks.update(_check_resolved_tasks(provider_name, registered_names, issues))
        _check_custom_task_api_routes(provider_name, registry_names, issues)

    return TaskHealthReport(
        checked_providers=selected,
        checked_tasks=len(checked_tasks),
        checked_bundles=checked_bundles,
        checked_aliases=checked_aliases,
        issues=_sort_issues(issues),
    )


def format_task_health_report(report: TaskHealthReport) -> str:
    """将自检结果格式化为适合 CLI 输出的文本。"""
    status = "PASS" if report.ok else "FAIL"
    lines = [
        f"Task registry health: {status}",
        (
            "checked_providers="
            f"{len(report.checked_providers)}, checked_tasks={report.checked_tasks}, "
            f"checked_bundles={report.checked_bundles}, checked_aliases={report.checked_aliases}, "
            f"errors={report.error_count}, warnings={report.warning_count}"
        ),
    ]
    for issue in report.issues:
        lines.append(
            f"[{issue.severity.upper()}] {issue.code} "
            f"{issue.provider}/{issue.subject}: {issue.message}"
        )
    return "\n".join(lines)


def _check_task_aliases(
    provider_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> int:
    count = 0
    for (alias_provider, alias_name), target in TASK_ALIASES.items():
        if alias_provider != provider_name:
            continue
        count += 1
        _check_task_reference(
            provider_name,
            f"alias:{alias_name}",
            target,
            registered_names,
            issues,
        )
        if alias_name == target:
            issues.append(
                _issue(
                    "error",
                    "self_alias",
                    provider_name,
                    alias_name,
                    "任务别名不能指向自身。",
                )
            )
    return count


def _check_task_bundles(
    provider_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> int:
    count = 0
    for bundle_name, tasks in TASK_BUNDLE_TASKS.get(provider_name, {}).items():
        count += 1
        _check_task_sequence(
            provider_name, f"bundle:{bundle_name}", tasks, registered_names, issues
        )
        if bundle_name in registered_names:
            issues.append(
                _issue(
                    "error",
                    "bundle_name_collides_with_task",
                    provider_name,
                    bundle_name,
                    "正式任务包名称不能与原子任务名称相同。",
                )
            )
    return count


def _check_task_bundle_aliases(
    provider_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> int:
    count = 0
    for (alias_provider, alias_name), tasks in TASK_BUNDLE_ALIASES.items():
        if alias_provider != provider_name:
            continue
        count += 1
        if alias_name in TASK_BUNDLE_TASKS.get(provider_name, {}):
            issues.append(
                _issue(
                    "error",
                    "bundle_alias_collides_with_formal_bundle",
                    provider_name,
                    alias_name,
                    "历史任务包别名不能与正式任务包名称相同。",
                )
            )
        _check_task_sequence(
            provider_name,
            f"bundle_alias:{alias_name}",
            tasks,
            registered_names,
            issues,
        )
    return count


def _check_industry_bundle_scope(
    provider_name: str,
    issues: list[TaskHealthIssue],
) -> None:
    """提示跨行业科技包与半导体专项包的覆盖边界。"""
    if provider_name != "industry":
        return
    bundles = TASK_BUNDLE_TASKS.get(provider_name, {})
    canonical = set(bundles.get("semiconductor_bundle", ()))
    technology = set(bundles.get("industry_tech_bundle", ()))
    missing = sorted(canonical - technology)
    if not missing or not (canonical & technology):
        return
    issues.append(
        _issue(
            "warning",
            "partial_semiconductor_bundle_coverage",
            provider_name,
            "industry_tech_bundle",
            "该包是跨行业科技观察包，缺少半导体专项端点 "
            f"[{', '.join(missing)}]；半导体周期采集请使用 semiconductor_bundle "
            "或 make sync-semiconductor。",
        )
    )


def _check_public_catalog(
    provider_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> set[tuple[str, str]]:
    checked: set[tuple[str, str]] = set()
    tasks = list_available_tasks(provider_name)
    seen: set[str] = set()
    for task_name in tasks:
        checked.add((provider_name, task_name))
        if task_name in seen:
            issues.append(
                _issue(
                    "error",
                    "duplicate_public_task",
                    provider_name,
                    task_name,
                    "公开任务目录中存在重复任务名。",
                )
            )
        seen.add(task_name)
        _check_task_reference(
            provider_name,
            "public_catalog",
            task_name,
            registered_names,
            issues,
        )
        if (provider_name, task_name) in TASK_ALIASES:
            issues.append(
                _issue(
                    "error",
                    "alias_exposed_as_public_task",
                    provider_name,
                    task_name,
                    "公开目录不应暴露历史别名。",
                )
            )
    return checked


def _check_resolved_tasks(
    provider_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> set[tuple[str, str]]:
    checked: set[tuple[str, str]] = set()
    for task_name in sorted(_candidate_task_names(provider_name, registered_names)):
        checked.add((provider_name, task_name))
        if task_name not in registered_names:
            issues.append(
                _issue(
                    "error",
                    "unregistered_task_candidate",
                    provider_name,
                    task_name,
                    "任务被任务包、别名或显式入口引用，但不在 Provider registry 或手工任务中。",
                )
            )
            continue
        try:
            spec = resolve_task(provider_name, task_name)
        except Exception as exc:
            issues.append(
                _issue(
                    "error",
                    "task_resolution_failed",
                    provider_name,
                    task_name,
                    str(exc),
                )
            )
            continue
        _check_task_spec(provider_name, task_name, spec, issues)
    return checked


def _check_custom_task_api_routes(
    provider_name: str,
    registry_names: set[str],
    issues: list[TaskHealthIssue],
) -> None:
    if not registry_names:
        return
    for (custom_provider, task_name), spec in CUSTOM_TASKS.items():
        if custom_provider != provider_name:
            continue
        if spec.task_name != task_name:
            continue
        if spec.api_name not in registry_names:
            issues.append(
                _issue(
                    "error",
                    "custom_task_api_missing",
                    provider_name,
                    task_name,
                    f"手工任务指向的上游 API [{spec.api_name}] 不在 Provider registry 中。",
                )
            )


def _check_task_sequence(
    provider_name: str,
    owner: str,
    tasks: Sequence[str],
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> None:
    if not tasks:
        issues.append(
            _issue("error", "empty_task_bundle", provider_name, owner, "任务包不能为空。")
        )
        return

    seen: set[str] = set()
    for task_name in tasks:
        if task_name in seen:
            issues.append(
                _issue(
                    "warning",
                    "duplicate_bundle_member",
                    provider_name,
                    owner,
                    f"任务包内重复引用 [{task_name}]，展开时会被去重。",
                )
            )
        seen.add(task_name)
        _check_task_reference(provider_name, owner, task_name, registered_names, issues)


def _check_task_reference(
    provider_name: str,
    owner: str,
    task_name: str,
    registered_names: set[str],
    issues: list[TaskHealthIssue],
) -> None:
    if not task_name.strip():
        issues.append(
            _issue("error", "blank_task_reference", provider_name, owner, "任务名不能为空。")
        )
        return
    if task_name in DISABLED_TASKS:
        issues.append(
            _issue(
                "error",
                "disabled_task_reference",
                provider_name,
                owner,
                f"引用了已停用任务 [{task_name}]。",
            )
        )
    if "/" in task_name:
        issues.append(
            _issue(
                "error",
                "upstream_path_reference",
                provider_name,
                owner,
                f"引用了上游路径 [{task_name}]，应使用项目短任务名。",
            )
        )
    if provider_name == "tushare" and is_tushare_internal_api(task_name):
        issues.append(
            _issue(
                "error",
                "internal_api_reference",
                provider_name,
                owner,
                f"引用了 TuShare 内部 API [{task_name}]，应使用项目任务名。",
            )
        )
    if (provider_name, task_name) in TASK_ALIASES:
        issues.append(
            _issue(
                "error",
                "non_canonical_task_reference",
                provider_name,
                owner,
                f"引用了历史别名 [{task_name}]，应使用 [{TASK_ALIASES[(provider_name, task_name)]}]。",
            )
        )
    if resolve_bundle_or_alias(provider_name, task_name) is not None:
        issues.append(
            _issue(
                "error",
                "bundle_referenced_as_task",
                provider_name,
                owner,
                f"引用了任务包 [{task_name}]，任务包成员必须是原子任务。",
            )
        )
    if task_name not in registered_names:
        issues.append(
            _issue(
                "error",
                "unknown_task_reference",
                provider_name,
                owner,
                f"引用了未注册任务 [{task_name}]。",
            )
        )


def _check_task_spec(
    provider_name: str,
    task_name: str,
    spec: TaskSpec,
    issues: list[TaskHealthIssue],
) -> None:
    if spec.provider != provider_name:
        issues.append(
            _issue(
                "error",
                "task_provider_mismatch",
                provider_name,
                task_name,
                f"TaskSpec.provider={spec.provider}，期望 {provider_name}。",
            )
        )
    if spec.task_name != task_name:
        issues.append(
            _issue(
                "error",
                "task_name_mismatch",
                provider_name,
                task_name,
                f"TaskSpec.task_name={spec.task_name}，期望 {task_name}。",
            )
        )
    if not spec.api_name:
        issues.append(
            _issue("error", "blank_api_name", provider_name, task_name, "api_name 不能为空。")
        )
    if not spec.dataset:
        issues.append(
            _issue("error", "blank_dataset", provider_name, task_name, "dataset 不能为空。")
        )
    if spec.fetch_mode not in _VALID_FETCH_MODES:
        issues.append(
            _issue(
                "error",
                "invalid_fetch_mode",
                provider_name,
                task_name,
                f"fetch_mode={spec.fetch_mode} 不在允许集合中。",
            )
        )
    if spec.frequency not in _VALID_FREQUENCIES:
        issues.append(
            _issue(
                "error",
                "invalid_frequency",
                provider_name,
                task_name,
                f"frequency={spec.frequency} 不在允许集合中。",
            )
        )
    if spec.sync_policy not in _VALID_SYNC_POLICIES:
        issues.append(
            _issue(
                "error",
                "invalid_sync_policy",
                provider_name,
                task_name,
                f"sync_policy={spec.sync_policy} 不在允许集合中。",
            )
        )
    if spec.watermark_column and spec.watermark_column not in spec.date_columns:
        issues.append(
            _issue(
                "error",
                "watermark_column_not_declared",
                provider_name,
                task_name,
                f"watermark_column={spec.watermark_column} 未出现在 date_columns 中。",
            )
        )


def _candidate_task_names(provider_name: str, registered_names: set[str]) -> set[str]:
    candidates = set(list_available_tasks(provider_name))
    candidates.update(task for provider, task in EXPLICIT_ONLY_TASKS if provider == provider_name)
    candidates.update(
        task
        for (provider, task), spec in CUSTOM_TASKS.items()
        if provider == provider_name and spec.task_name == task
    )
    for tasks in TASK_BUNDLE_TASKS.get(provider_name, {}).values():
        candidates.update(tasks)
    for (alias_provider, _), target in TASK_ALIASES.items():
        if alias_provider == provider_name:
            candidates.add(target)
    for (alias_provider, _), tasks in TASK_BUNDLE_ALIASES.items():
        if alias_provider == provider_name:
            candidates.update(tasks)
    return candidates - DISABLED_TASKS


def _registered_task_names(provider_name: str, registry_names: set[str]) -> set[str]:
    names = set(registry_names)
    names.update(
        task
        for (provider, task), spec in CUSTOM_TASKS.items()
        if provider == provider_name and spec.task_name == task
    )
    return names


def _load_registry_names(provider_name: str, issues: list[TaskHealthIssue]) -> set[str]:
    try:
        return set(provider_registry(provider_name))
    except Exception as exc:
        issues.append(
            _issue(
                "error",
                "provider_registry_load_failed",
                provider_name,
                provider_name,
                str(exc),
            )
        )
        return set()


def _sort_issues(issues: Iterable[TaskHealthIssue]) -> tuple[TaskHealthIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                _SEVERITY_ORDER[issue.severity],
                issue.provider,
                issue.code,
                issue.subject,
                issue.message,
            ),
        )
    )


def _issue(
    severity: TaskHealthSeverity,
    code: str,
    provider: str,
    subject: str,
    message: str,
) -> TaskHealthIssue:
    return TaskHealthIssue(
        severity=severity,
        code=code,
        provider=provider,
        subject=subject,
        message=message,
    )


__all__ = [
    "TaskHealthIssue",
    "TaskHealthReport",
    "format_task_health_report",
    "known_task_providers",
    "run_task_health_checks",
]
