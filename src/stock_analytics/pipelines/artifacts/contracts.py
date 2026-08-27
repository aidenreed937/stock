"""共享产物存储契约。"""

from __future__ import annotations

from typing import Literal

RunClass = Literal["official", "backfill", "experiment"]
RUN_CLASSES: tuple[RunClass, ...] = ("official", "backfill", "experiment")


def normalize_run_class(value: str) -> RunClass:
    """校验并规范化产物运行分类。"""
    if value == "official":
        return "official"
    if value == "backfill":
        return "backfill"
    if value == "experiment":
        return "experiment"
    raise ValueError(f"run_class 必须是 {RUN_CLASSES} 之一: {value!r}")


__all__ = ["RUN_CLASSES", "RunClass", "normalize_run_class"]
