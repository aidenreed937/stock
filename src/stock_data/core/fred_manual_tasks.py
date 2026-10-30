"""FRED 项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MakeTaskSpec = Callable[..., Any]


def build_fred_manual_tasks(make_spec: MakeTaskSpec) -> dict[tuple[str, str], Any]:
    """生成 FRED 需要项目短任务名或显式调度契约的任务。"""
    return {}


__all__ = ["build_fred_manual_tasks"]
