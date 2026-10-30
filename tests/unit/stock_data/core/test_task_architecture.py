"""任务注册层的架构边界测试。"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
STOCK_DATA_ROOT = PROJECT_ROOT / "src" / "stock_data"
STOCK_DATA_TESTS_ROOT = PROJECT_ROOT / "tests" / "unit" / "stock_data"
TASK_REGISTRY_MODULE = "stock_data.core.task_registry"
TASK_REGISTRY_HELPERS_MODULE = "stock_data.core.task_registry_helpers"
ALLOWED_TASK_REGISTRY_IMPORTERS = {
    STOCK_DATA_ROOT / "core" / "task_registry.py",
    STOCK_DATA_TESTS_ROOT / "core" / "test_task_registry_facade.py",
}
ALLOWED_TASK_REGISTRY_HELPER_IMPORTERS = {
    STOCK_DATA_ROOT / "core" / "task_registry_helpers.py",
}


def test_stock_data_modules_do_not_depend_on_task_registry_facade() -> None:
    """内部模块和非兼容测试不得继续依赖 `task_registry` 兼容门面。"""
    offenders: list[str] = []
    paths = [*STOCK_DATA_ROOT.rglob("*.py"), *STOCK_DATA_TESTS_ROOT.rglob("*.py")]
    for path in sorted(paths):
        if path in ALLOWED_TASK_REGISTRY_IMPORTERS:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == TASK_REGISTRY_MODULE:
                names = ", ".join(alias.name for alias in node.names)
                rel_path = path.relative_to(PROJECT_ROOT)
                offenders.append(f"{rel_path}:{node.lineno} -> from import {names}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == TASK_REGISTRY_MODULE:
                        rel_path = path.relative_to(PROJECT_ROOT)
                        offenders.append(f"{rel_path}:{node.lineno} -> import {alias.name}")

    assert not offenders, "stock_data 内部禁止导入 task_registry 兼容门面:\n" + "\n".join(offenders)


def test_stock_data_modules_use_specific_task_helper_modules() -> None:
    """内部模块不得继续依赖 `task_registry_helpers` 混合兼容入口。"""
    offenders: list[str] = []
    paths = [*STOCK_DATA_ROOT.rglob("*.py"), *STOCK_DATA_TESTS_ROOT.rglob("*.py")]
    for path in sorted(paths):
        if path in ALLOWED_TASK_REGISTRY_HELPER_IMPORTERS:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == TASK_REGISTRY_HELPERS_MODULE:
                names = ", ".join(alias.name for alias in node.names)
                rel_path = path.relative_to(PROJECT_ROOT)
                offenders.append(f"{rel_path}:{node.lineno} -> from import {names}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == TASK_REGISTRY_HELPERS_MODULE:
                        rel_path = path.relative_to(PROJECT_ROOT)
                        offenders.append(f"{rel_path}:{node.lineno} -> import {alias.name}")

    assert not offenders, "stock_data 内部应导入具体任务辅助模块:\n" + "\n".join(offenders)


def test_task_derivation_does_not_depend_on_legacy_task_name_whitelists() -> None:
    """通用推导层不应再靠中心任务名白名单决定调度语义。"""
    source = (STOCK_DATA_ROOT / "core" / "task_derivation.py").read_text()
    forbidden_terms = {
        "PER_PERIOD_DATASETS",
        "NON_SINGLE_SYNC_DATASETS",
        "PARTITIONED_EVENT_TASKS",
        'provider_name == "lixinger"',
        'provider_name == "tushare"',
        '"margin_detail"',
        '"fund_share"',
        '"forecast"',
        '"express"',
        '"hk_hold"',
    }
    offenders = sorted(term for term in forbidden_terms if term in source)

    assert not offenders, "任务调度事实应下沉到 Provider 元数据或显式 TaskSpec: " + ", ".join(
        offenders
    )


def test_task_resolution_does_not_query_fetcher_registries_for_market() -> None:
    """任务解析入口不应直接内联各 Provider 的市场归属查询。"""
    path = STOCK_DATA_ROOT / "core" / "task_resolution.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("stock_data.fetcher."):
                names = ", ".join(alias.name for alias in node.names)
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} -> {names}")

    source = path.read_text()
    forbidden_registry_names = {
        "TUSHARE_API_REGISTRY",
        "YFINANCE_API_REGISTRY",
        "LIXINGER_API_REGISTRY",
        "FRED_API_REGISTRY",
        "ALPHAVANTAGE_API_REGISTRY",
    }
    offenders.extend(sorted(name for name in forbidden_registry_names if name in source))

    assert not offenders, "市场归属查询应由 task_market.py 负责:\n" + "\n".join(offenders)


def test_task_resolution_delegates_task_catalog_listing() -> None:
    """公开任务枚举不应继续内联在单任务解析入口。"""
    path = STOCK_DATA_ROOT / "core" / "task_resolution.py"
    tree = ast.parse(path.read_text(), filename=str(path))

    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "list_available_tasks" not in function_names


def test_task_resolution_delegates_task_name_rules() -> None:
    """任务名保护和别名规则不应继续内联在 TaskSpec 合成入口。"""
    source = (STOCK_DATA_ROOT / "core" / "task_resolution.py").read_text()
    forbidden_terms = {
        "DISABLED_TASKS",
        "resolve_bundle_or_alias",
        "is_tushare_internal_api",
        "removesuffix",
    }
    offenders = sorted(term for term in forbidden_terms if term in source)

    assert not offenders, "任务名规则应由 task_name_rules.py 负责: " + ", ".join(offenders)


def test_task_health_module_does_not_depend_on_pipeline_runtime() -> None:
    """任务注册健康检查应保持只读配置层能力，不依赖 Pipeline 运行时。"""
    path = STOCK_DATA_ROOT / "core" / "task_health.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    forbidden_prefixes = (
        "stock_data.pipeline",
        "stock_data.storage",
        "stock_data.governance",
        "stock_cli",
    )
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(forbidden_prefixes):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} -> {node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_prefixes):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} -> {alias.name}"
                    )

    assert not offenders, "task_health.py 不应依赖运行时管线、存储或 CLI:\n" + "\n".join(offenders)


def test_industry_task_contracts_and_bundles_stay_split() -> None:
    """行业任务字段契约和任务包清单应分开增长。"""
    from stock_data.core.industry_bundle_specs import INDUSTRY_TASK_BUNDLE_TASKS
    from stock_data.core.industry_task_specs import INDUSTRY_TASK_ORDER, INDUSTRY_TASK_SPECS

    industry_tasks_source = (STOCK_DATA_ROOT / "core" / "industry_tasks.py").read_text()
    assert "INDUSTRY_TASK_BUNDLE_TASKS" not in industry_tasks_source

    task_names = tuple(str(item["task"]) for item in INDUSTRY_TASK_SPECS)
    assert task_names == INDUSTRY_TASK_ORDER
    assert len(task_names) == len(set(task_names))

    bundle_members = {task for tasks in INDUSTRY_TASK_BUNDLE_TASKS.values() for task in tasks}
    assert bundle_members <= set(task_names)


def test_semiconductor_bundle_covers_the_13_registered_endpoints() -> None:
    from stock_data.core.industry_bundle_specs import INDUSTRY_TASK_BUNDLE_TASKS
    from stock_data.core.task_bundles import resolve_bundle

    assert INDUSTRY_TASK_BUNDLE_TASKS["semiconductor_bundle"] == (
        "semiconductor_sales",
        "semiconductor_lead",
        "semiconductor_inventory_days",
        "semiconductor_channel_inventory",
        "semiconductor_equipment",
        "semiconductor_equipment_semi",
        "foundry_capacity_utilization",
        "chip_lead_time",
        "tsmc_advanced_packaging_revenue",
        "tsmc_cowos_capacity_estimates",
        "semiconductor_memory_price",
        "semiconductor_memory_benchmark",
        "semiconductor_memory_taiwan_lead",
    )
    assert "cloud_capex_quarterly" not in INDUSTRY_TASK_BUNDLE_TASKS["semiconductor_bundle"]
    assert "consumer_electronics" not in INDUSTRY_TASK_BUNDLE_TASKS["semiconductor_bundle"]
    assert (
        resolve_bundle("industry", "semiconductor").tasks
        == INDUSTRY_TASK_BUNDLE_TASKS["semiconductor_bundle"]
    )
    assert (
        resolve_bundle("industry", "semiconductor_core").tasks
        == INDUSTRY_TASK_BUNDLE_TASKS["semiconductor_bundle"]
    )
