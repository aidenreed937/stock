"""共享产物存储契约。"""

from __future__ import annotations

from typing import Literal, cast

RunClass = Literal["official", "backfill", "experiment"]
RUN_CLASSES: tuple[RunClass, ...] = ("official", "backfill", "experiment")


def normalize_run_class(value: str) -> RunClass:
    """校验并规范化产物运行分类。"""
    if value not in RUN_CLASSES:
        raise ValueError(f"run_class 必须是 {RUN_CLASSES} 之一: {value!r}")
    return cast(RunClass, value)


__all__ = ["RUN_CLASSES", "RunClass", "normalize_run_class"]
