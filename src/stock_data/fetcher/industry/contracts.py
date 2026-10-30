"""垂直产业端点执行契约。"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.core.runtime import DataRuntimeContext


@dataclass(frozen=True)
class IndustryRunContext:
    """单个产业端点的一次运行上下文。"""

    endpoint: str
    raw_dir: Path
    curated_dir: Path
    start_date: date | None = None
    end_date: date | None = None
    force_refresh: bool = False
    refresh_raw_cache: bool = False
    runtime: DataRuntimeContext | None = None


class IndustryCollectionResult(list[Any]):
    """采集器返回的可审计结果，同时保持旧 ``list`` 接口兼容。

    ``records`` 仍然可以像普通列表一样迭代、切片和与 ``[]`` 比较；新增的状态字段
    用于让 runner 区分在线获取、缓存命中、范围缺失和真正的失败。
    """

    def __init__(
        self,
        records: Iterable[Any] = (),
        *,
        status: str = "SUCCESS",
        fetched_periods: Iterable[str] = (),
        cached_periods: Iterable[str] = (),
        missing_periods: Iterable[str] = (),
        errors: Iterable[str] = (),
        updated: bool = False,
    ) -> None:
        super().__init__(records)
        self.status = status
        self.fetched_periods = tuple(fetched_periods)
        self.cached_periods = tuple(cached_periods)
        self.missing_periods = tuple(missing_periods)
        self.errors = tuple(errors)
        self.updated = updated

    @property
    def records(self) -> list[Any]:
        """返回普通列表视图，便于序列化和旧调用方使用。"""
        return list(self)

    @property
    def record_count(self) -> int:
        return len(self)


@dataclass(frozen=True)
class IndustryFrameResult:
    """DataFrame 采集器的可审计结果。"""

    frame: pl.DataFrame
    status: str = "SUCCESS"
    fetched_periods: tuple[str, ...] = ()
    cached_periods: tuple[str, ...] = ()
    missing_periods: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    updated: bool = False


class IndustryRunResult(int):
    """产业端点执行结果，数值行为兼容旧的落盘行数返回值。"""

    status: str
    updated: bool
    fetched_periods: tuple[str, ...]
    cached_periods: tuple[str, ...]
    missing_periods: tuple[str, ...]
    errors: tuple[str, ...]

    def __new__(
        cls,
        records: int = 0,
        *,
        status: str = "SUCCESS",
        updated: bool = False,
        fetched_periods: Iterable[str] = (),
        cached_periods: Iterable[str] = (),
        missing_periods: Iterable[str] = (),
        errors: Iterable[str] = (),
    ) -> "IndustryRunResult":
        value = int.__new__(cls, records)
        value.status = status
        value.updated = updated
        value.fetched_periods = tuple(fetched_periods)
        value.cached_periods = tuple(cached_periods)
        value.missing_periods = tuple(missing_periods)
        value.errors = tuple(errors)
        return value

    @property
    def records(self) -> int:
        return int(self)


IndustryEndpointRunner = Callable[[IndustryRunContext], int | IndustryRunResult]


def as_collection_result(value: Any) -> IndustryCollectionResult:
    """将旧版列表采集结果统一为结构化契约。"""
    if isinstance(value, IndustryCollectionResult):
        return value
    if value is None:
        return IndustryCollectionResult([], status="EMPTY")
    if isinstance(value, Iterator):
        value = list(value)
    if isinstance(value, list | tuple):
        return IndustryCollectionResult(value, updated=bool(value))
    raise TypeError(f"产业采集器返回了不支持的结果类型: {type(value)!r}")


@dataclass(frozen=True)
class IndustryEndpointSpec:
    """单个产业端点的注册规格。"""

    endpoint: str
    domain: str
    run: IndustryEndpointRunner
    target_file: str = ""
    raw_subdir: str = ""
    raw_target_file: str = ""
