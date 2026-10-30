"""任务包的稳定领域类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskBundle:
    """一组可由调度入口展开的原子项目任务。"""

    bundle_name: str
    provider: str
    tasks: tuple[str, ...]


__all__ = ["TaskBundle"]
