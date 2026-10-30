"""产业离线重放计划的共享支撑（端点路径解析 + 计划条目构造）。

各产业包在 ``<pkg>/replay.py`` 中自持自己的重放计划，Curated/RAW 路径统一由该产业
``registry.ENDPOINT_SPECS`` 的 ``target_file`` / ``raw_subdir`` 推导，禁止在计划里
硬编码目录字符串；未在注册表中登记的派生表（如 hook 产物）用显式 ``curated`` 传参。

路径解析与条目构造放在此模块，避免十几个产业包各自复制同一套逻辑。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock_data.fetcher.industry.contracts import IndustryEndpointSpec

__all__ = [
    "csv_collector_loader",
    "endpoint_paths",
    "identity_frame",
    "raw_csv_loader",
    "replay_entry",
]


def endpoint_paths(
    specs: Sequence[IndustryEndpointSpec],
    endpoint: str,
) -> tuple[str, str]:
    """返回端点的 ``(Curated 相对路径, RAW 子目录)``，取自端点注册表。

    RAW 子目录允许为空串（该端点不落 RAW 时条目里会省略该键）。
    """
    for spec in specs:
        if spec.endpoint == endpoint:
            if not spec.target_file:
                raise KeyError(f"端点 [{endpoint}] 未声明 target_file")
            return spec.target_file, spec.raw_subdir or ""
    raise KeyError(f"端点未注册: {endpoint}")


def replay_entry(
    endpoint: str,
    *,
    loader: Any,
    to_frame: Any,
    raw_to_frame: Any = None,
    primary_keys: list[str] | None = None,
    specs: Sequence[IndustryEndpointSpec] | None = None,
    curated: str | None = None,
    raw_subdir: str | None = None,
    loader_uses_curated: bool = False,
) -> dict[str, Any]:
    """构造单条重放计划。

    - ``curated`` 省略时由 ``specs``（该产业 ``ENDPOINT_SPECS``）推导；未登记的
      派生表必须显式传入 ``curated``。
    - ``raw_subdir`` 为空时不写入该键，以保持重放脚本对 RAW 落点的既有默认行为。
    - 仅当 ``raw_to_frame`` 非空时才写入该键。
    """
    if curated is None:
        if specs is None:
            raise ValueError(f"端点 [{endpoint}] 未提供 curated 且缺少 specs 无法推导")
        curated, registry_raw_subdir = endpoint_paths(specs, endpoint)
        if raw_subdir is None:
            raw_subdir = registry_raw_subdir

    entry: dict[str, Any] = {
        "loader": loader,
        "to_frame": to_frame,
        "curated": curated,
        "primary_keys": primary_keys,
    }
    if raw_to_frame is not None:
        entry["raw_to_frame"] = raw_to_frame
    if raw_subdir:
        entry["raw_subdir"] = raw_subdir
    if loader_uses_curated:
        entry["loader_uses_curated"] = True
    return entry


def identity_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """派生表重放用恒等转换（loader 已直接产出最终帧）。"""
    return frame


def csv_collector_loader(collector_cls: type, rel_path: str) -> Any:
    """构造「按 RAW 下相对路径 CSV 收集」的 loader（``collector.load_from_raw_csv``）。"""

    def loader(raw_root: Path) -> list[Any]:
        collector = collector_cls(raw_dir=raw_root)
        return list(collector.load_from_raw_csv(raw_root / rel_path))

    return loader


def raw_csv_loader(load_func: Any, rel_path: str) -> Any:
    """构造「用解析函数读 RAW 下相对路径 CSV」的 loader。"""

    def loader(raw_root: Path) -> list[Any]:
        return list(load_func(raw_root / rel_path))

    return loader
