"""`task_registry` 旧导入路径兼容测试。"""

from __future__ import annotations

from stock_data.core.task_registry import (
    expand_task_targets,
    list_available_bundles,
    list_available_tasks,
    resolve_bundle,
    resolve_public_task,
    resolve_task,
)


def test_task_registry_facade_keeps_legacy_imports_working() -> None:
    """旧调用方仍可通过 `task_registry` 获取稳定任务能力。"""
    task = resolve_task("tushare", "stock_daily_bar")

    assert task.api_name == "daily"
    assert resolve_public_task("tushare", "stock_daily_bar").dataset == "stock_daily_bar"
    assert "stock_daily_bar" in list_available_tasks("tushare")
    assert "daily_market_bundle" in list_available_bundles("tushare")
    assert resolve_bundle("tushare", "daily_market_bundle").tasks[0] == "stock_daily_bar"
    assert expand_task_targets("tushare", ["index_daily", "index_daily_bar"]) == ["index_daily_bar"]
