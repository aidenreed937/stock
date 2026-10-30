"""垂直产业端点通用执行器。"""

from collections.abc import Callable, Mapping
from datetime import timedelta
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.contracts import (
    IndustryCollectionResult,
    IndustryEndpointSpec,
    IndustryFrameResult,
    IndustryRunContext,
    IndustryRunResult,
    as_collection_result,
)
from stock_data.fetcher.industry.curated_store import save_curated_dataset

RecordCollector = Callable[..., Any]
RecordTransformer = Callable[..., pl.DataFrame]
FrameCollector = Callable[[Path, bool], pl.DataFrame]
ContextFrameCollector = Callable[[IndustryRunContext], pl.DataFrame]
AfterSuccessHook = Callable[[IndustryRunContext, int], None]


def collector(
    factory: Callable[..., Any],
    method: str = "collect",
    *,
    constructor_kwargs: Mapping[str, Any] | None = None,
) -> RecordCollector:
    """生成统一 raw_path/force 采集入口。"""

    def run(
        raw_path: Path,
        force: bool,
        start_date: Any = None,
        end_date: Any = None,
    ) -> Any:
        target = factory(raw_dir=raw_path, **dict(constructor_kwargs or {}))
        collect = getattr(target, method)
        parameters = signature(collect).parameters
        accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
        kwargs: dict[str, Any] = {}
        if accepts_kwargs or "force" in parameters:
            kwargs["force"] = force
        if accepts_kwargs or "start_date" in parameters:
            kwargs["start_date"] = start_date
        if accepts_kwargs or "end_date" in parameters:
            kwargs["end_date"] = end_date
        return collect(**kwargs) if kwargs else collect()

    return run


def context_collector(
    factory: Callable[..., Any],
    method: str = "collect",
    *,
    constructor_kwargs: Mapping[str, Any] | None = None,
) -> ContextFrameCollector:
    """生成可接收完整 IndustryRunContext 的采集入口。"""

    def run(context: IndustryRunContext) -> Any:
        target = factory(raw_dir=context.raw_dir, **dict(constructor_kwargs or {}))
        collect = getattr(target, method)
        parameters = signature(collect).parameters
        accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
        kwargs: dict[str, Any] = {}
        context_kwargs = {
            "force": context.force_refresh or context.refresh_raw_cache,
            "start_date": context.start_date,
            "end_date": context.end_date,
        }
        for name, value in context_kwargs.items():
            if accepts_kwargs or name in parameters:
                kwargs[name] = value
        return collect(**kwargs) if kwargs else collect()

    return run


FrameTransformer = Callable[[pl.DataFrame], pl.DataFrame]


def record_endpoint(
    *,
    endpoint: str,
    domain: str,
    collect: RecordCollector,
    transform: RecordTransformer,
    target_file: str,
    primary_keys: list[str] | None,
    raw_subdir: str = "",
    raw_target_file: str | None = None,
    raw_transform: RecordTransformer | None = None,
    raw_primary_keys: list[str] | None = None,
    after_success: AfterSuccessHook | None = None,
    force_refresh_on_gap: bool = False,
    require_context_coverage: bool = False,
    context_coverage_tolerance_days: int = 0,
    context_coverage_frequency: str | None = None,
) -> IndustryEndpointSpec:
    """注册 records -> DataFrame -> Curated Parquet 类型端点。"""

    def run(context: IndustryRunContext) -> IndustryRunResult:
        has_requested_range = context.start_date is not None or context.end_date is not None
        # ``force_refresh_on_gap`` only bypasses the source cache for the requested window;
        # collectors must still honor start_date/end_date and must not refresh their full history.
        refresh = (
            context.force_refresh
            or context.refresh_raw_cache
            or (force_refresh_on_gap and has_requested_range)
        )
        collection = as_collection_result(
            _call_record_collector(collect, context, force_refresh=refresh)
        )
        if not collection:
            return _collection_run_result(collection)
        records = collection.records
        existing_curated = _load_existing_curated(transform, context.curated_dir / target_file)
        curated_df = _call_transform(
            transform,
            records,
            context,
            existing_df=existing_curated,
        )
        if require_context_coverage and not _has_context_coverage(
            curated_df,
            context,
            context_coverage_tolerance_days,
            context_coverage_frequency,
        ):
            return IndustryRunResult(
                0,
                status="MISSING_RANGE",
                fetched_periods=collection.fetched_periods,
                cached_periods=collection.cached_periods,
                missing_periods=collection.missing_periods,
                errors=collection.errors,
            )
        if raw_subdir:
            if raw_transform is None:
                raise ValueError(f"端点 {endpoint} 配置了 raw_subdir，但未配置 raw_transform")
            target_name = raw_target_file or Path(target_file).name
            raw_target_path = context.raw_dir / raw_subdir / target_name
            save_curated_dataset(
                _call_transform(raw_transform, records, context),
                raw_target_path,
                primary_keys=raw_primary_keys or primary_keys,
            )
        target_path = context.curated_dir / target_file
        previous_df = pl.read_parquet(target_path) if target_path.exists() else None
        count = save_curated_dataset(
            curated_df,
            target_path,
            primary_keys=primary_keys,
        )
        updated = _frames_differ(previous_df, pl.read_parquet(target_path))
        status = _collection_status(collection, updated=updated)
        if after_success is not None and count and status == "SUCCESS":
            after_success(context, count)
        return IndustryRunResult(
            count,
            status=status,
            updated=updated,
            fetched_periods=collection.fetched_periods,
            cached_periods=collection.cached_periods,
            missing_periods=collection.missing_periods,
            errors=collection.errors,
        )

    return IndustryEndpointSpec(
        endpoint=endpoint,
        domain=domain,
        run=run,
        target_file=target_file,
        raw_subdir=raw_subdir,
        raw_target_file=raw_target_file or target_file if raw_subdir else "",
    )


def _call_record_collector(
    collect: Callable[..., Any], context: IndustryRunContext, *, force_refresh: bool | None = None
) -> Any:
    """按采集器签名传递运行窗口，兼容旧的两参数自定义采集入口。"""
    parameters = signature(collect).parameters
    accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
    kwargs: dict[str, Any] = {}
    if accepts_kwargs or "start_date" in parameters:
        kwargs["start_date"] = context.start_date
    if accepts_kwargs or "end_date" in parameters:
        kwargs["end_date"] = context.end_date
    refresh = context.force_refresh if force_refresh is None else force_refresh
    return collect(context.raw_dir, refresh, **kwargs)


def _collection_run_result(collection: IndustryCollectionResult) -> IndustryRunResult:
    """将空采集结果转换为可供同步层判定的执行结果。"""
    status = collection.status or "EMPTY"
    if status == "SUCCESS":
        status = "EMPTY"
    return IndustryRunResult(
        0,
        status=status,
        fetched_periods=collection.fetched_periods,
        cached_periods=collection.cached_periods,
        missing_periods=collection.missing_periods,
        errors=collection.errors,
    )


def _collection_status(collection: IndustryCollectionResult, *, updated: bool) -> str:
    """根据采集器结果和实际落盘变化确定端点状态。"""
    if collection.status == "NO_CHANGE":
        return "SUCCESS" if updated else "NO_CHANGE"
    if collection.status and collection.status != "SUCCESS":
        return collection.status
    if collection.missing_periods:
        return "PARTIAL"
    return "SUCCESS" if updated else "NO_CHANGE"


def _frames_differ(before: pl.DataFrame | None, after: pl.DataFrame) -> bool:
    """比较落盘前后事实帧，避免用合并后的总行数冒充本次更新。"""
    if before is None:
        return not after.is_empty()
    if before.columns != after.columns or before.schema != after.schema:
        return True
    return not before.equals(after)


def _has_context_coverage(
    frame: pl.DataFrame,
    context: IndustryRunContext,
    tolerance_days: int,
    frequency: str | None = None,
) -> bool:
    """判断结果是否覆盖本次同步目标，防止旧全表被当作新结果。"""
    if context.start_date is None and context.end_date is None:
        return True
    if frame.is_empty() or "trade_date" not in frame.columns:
        return False
    target = context.end_date or context.start_date
    if target is None:
        return False
    tolerance = timedelta(days=max(tolerance_days, 0))
    if frequency == "weekly":
        period_start = target - timedelta(days=target.weekday())
        lower = period_start - tolerance
        upper = period_start + timedelta(days=6) + tolerance
    else:
        lower = target - tolerance
        upper = target + tolerance
    return (
        frame.filter(
            (pl.col("trade_date") >= pl.lit(lower)) & (pl.col("trade_date") <= pl.lit(upper))
        ).height
        > 0
    )


def _call_transform(
    transform: Callable[..., pl.DataFrame],
    value: Any,
    context: IndustryRunContext,
    *,
    existing_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """向支持运行时或历史输入的转换器注入执行上下文。"""
    parameters = signature(transform).parameters
    accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
    kwargs: dict[str, Any] = {}
    if accepts_kwargs or "runtime" in parameters:
        kwargs["runtime"] = context.runtime
    if "existing_df" in parameters:
        kwargs["existing_df"] = existing_df
    return transform(value, **kwargs) if kwargs else transform(value)


def _load_existing_curated(
    transform: Callable[..., pl.DataFrame], target_path: Path
) -> pl.DataFrame | None:
    """仅为声明需要历史的转换器读取既有 Curated。"""
    if "existing_df" not in signature(transform).parameters or not target_path.exists():
        return None
    return pl.read_parquet(target_path)


def frame_endpoint(
    *,
    endpoint: str,
    domain: str,
    collect: FrameCollector | None = None,
    context_collect: ContextFrameCollector | None = None,
    target_file: str,
    primary_keys: list[str],
    transform: FrameTransformer | None = None,
    raw_subdir: str = "",
    raw_target_file: str | None = None,
    raw_transform: FrameTransformer | None = None,
    raw_primary_keys: list[str] | None = None,
    require_context_coverage: bool = False,
    context_coverage_tolerance_days: int = 0,
    context_coverage_frequency: str | None = None,
) -> IndustryEndpointSpec:
    """注册 DataFrame -> Curated Parquet 类型端点。"""

    def run(context: IndustryRunContext) -> IndustryRunResult:
        if context_collect is not None:
            collected = context_collect(context)
            frame_result = collected if isinstance(collected, IndustryFrameResult) else None
            df = frame_result.frame if frame_result is not None else collected
        elif collect is not None:
            frame_result = None
            df = collect(context.raw_dir, context.force_refresh or context.refresh_raw_cache)
        else:
            raise ValueError(f"端点 {endpoint} 未配置采集入口")
        if df.is_empty():
            if frame_result is None or frame_result.status == "SUCCESS":
                return IndustryRunResult(0, status="EMPTY")
            return IndustryRunResult(
                0,
                status=frame_result.status,
                fetched_periods=frame_result.fetched_periods,
                cached_periods=frame_result.cached_periods,
                missing_periods=frame_result.missing_periods,
                errors=frame_result.errors,
            )
        if raw_subdir and raw_transform is None:
            raise ValueError(f"端点 {endpoint} 配置了 raw_subdir，但未配置 raw_transform")
        raw_df = raw_transform(df) if raw_subdir and raw_transform is not None else df
        if raw_subdir:
            target_name = raw_target_file or Path(target_file).name
            raw_target_path = context.raw_dir / raw_subdir / target_name
            save_curated_dataset(
                raw_df,
                raw_target_path,
                primary_keys=raw_primary_keys or primary_keys,
            )
        target_path = context.curated_dir / target_file
        existing_curated = (
            _load_existing_curated(transform, target_path) if transform is not None else None
        )
        curated_df = (
            _call_transform(
                transform,
                raw_df,
                context,
                existing_df=existing_curated,
            )
            if transform is not None
            else raw_df
        )
        if require_context_coverage and not _has_context_coverage(
            curated_df,
            context,
            context_coverage_tolerance_days,
            context_coverage_frequency,
        ):
            return IndustryRunResult(0, status="MISSING_RANGE")
        previous_df = pl.read_parquet(target_path) if target_path.exists() else None
        count = save_curated_dataset(curated_df, target_path, primary_keys=primary_keys)
        updated = _frames_differ(previous_df, pl.read_parquet(target_path))
        status = "SUCCESS" if updated else "NO_CHANGE"
        if frame_result is not None:
            if frame_result.status != "SUCCESS":
                status = frame_result.status
            elif frame_result.missing_periods:
                status = "PARTIAL"
        return IndustryRunResult(
            count,
            status=status,
            updated=updated,
            fetched_periods=frame_result.fetched_periods if frame_result else (),
            cached_periods=frame_result.cached_periods if frame_result else (),
            missing_periods=frame_result.missing_periods if frame_result else (),
            errors=frame_result.errors if frame_result else (),
        )

    return IndustryEndpointSpec(
        endpoint=endpoint,
        domain=domain,
        run=run,
        target_file=target_file,
        raw_subdir=raw_subdir,
        raw_target_file=raw_target_file or target_file if raw_subdir else "",
    )


def run_endpoint(spec: IndustryEndpointSpec, context: IndustryRunContext) -> IndustryRunResult:
    """执行已注册的产业端点。"""
    context.curated_dir.mkdir(parents=True, exist_ok=True)
    result = spec.run(context)
    if isinstance(result, IndustryRunResult):
        return result
    count = int(result)
    return IndustryRunResult(
        count,
        status="SUCCESS" if count > 0 else "EMPTY",
        updated=count > 0,
    )
