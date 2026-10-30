"""源表同步后的 Curated 派生数据集刷新。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext
from stock_data.pipeline.index_member_versioned import (
    INDEX_MEMBER_VERSIONED_DATASET,
    materialize_index_member_versioned,
)
from stock_data.pipeline.sw_industry_golden import (
    SW_INDUSTRY_MEMBER_GOLDEN_DATASET,
    materialize_sw_2021_industry_golden,
)
from stock_data.pipeline.sync_models import SyncExecutionResult, SyncTaskItem

_EQUIPMENT_GM_SOURCE_TASKS = frozenset(
    {
        "semiconductor_equipment_gm_amat",
        "semiconductor_equipment_gm_lrcx",
        "semiconductor_equipment_gm_klac",
        "tel_gm_quarterly",
    }
)
_EQUIPMENT_GM_COMPANIES = {
    "semiconductor_equipment_gm_amat": "AMAT",
    "semiconductor_equipment_gm_lrcx": "LRCX",
    "semiconductor_equipment_gm_klac": "KLAC",
    "tel_gm_quarterly": "TEL",
}
_EQUIPMENT_GM_TARGET = "semiconductor/equipment/semiconductor_equipment_gm_multi.parquet"

_INDEX_MEMBER_VERSIONED_SOURCE_TASKS = frozenset({"index_classify", "index_member"})
_SUCCESS_STATUS = "SUCCESS"
_UP_TO_DATE_STATUS = "UP_TO_DATE"
_SW_INDUSTRY_GOLDEN_SOURCE_TASKS = {
    "tushare": frozenset({"index_classify", "index_member"}),
    "lixinger": frozenset({"sw_2021_constituents"}),
}


def refresh_tushare_index_member_versioned(
    plan: Sequence[SyncTaskItem],
    results: Sequence[SyncExecutionResult],
    *,
    runtime: DataRuntimeContext | None = None,
) -> SyncExecutionResult | None:
    """在申万源表同步成功后重建版本化成分表。"""
    relevant_plan = [item for item in plan if item.endpoint in _INDEX_MEMBER_VERSIONED_SOURCE_TASKS]
    if not relevant_plan:
        return None

    successful_results = [
        result
        for result in results
        if result.endpoint in _INDEX_MEMBER_VERSIONED_SOURCE_TASKS
        and result.status == _SUCCESS_STATUS
    ]
    if not successful_results:
        return None

    start_date = min(result.start_date for result in successful_results)
    end_date = max(result.end_date for result in successful_results)
    if not _source_tasks_ready(relevant_plan, results):
        error = "index_member_versioned 自动重建被阻断：相关源表未全部成功或已是最新"
        logger.warning(error)
        return SyncExecutionResult(
            data_source="tushare",
            endpoint=INDEX_MEMBER_VERSIONED_DATASET,
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=0.0,
            status="BLOCKED",
            error=error,
        )

    started = perf_counter()
    try:
        frame = materialize_index_member_versioned(runtime=runtime)
        if frame.is_empty():
            raise ValueError("index_member_versioned 重建结果为空，保留旧表")
    except Exception as exc:
        error = f"自动重建 {INDEX_MEMBER_VERSIONED_DATASET} 失败: {exc}"
        logger.error(error)
        return SyncExecutionResult(
            data_source="tushare",
            endpoint=INDEX_MEMBER_VERSIONED_DATASET,
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=round(perf_counter() - started, 2),
            status="FAILED",
            error=error,
        )

    logger.info(f"源表同步成功，自动重建 {INDEX_MEMBER_VERSIONED_DATASET} 完成 [{frame.height} 行]")
    return SyncExecutionResult(
        data_source="tushare",
        endpoint=INDEX_MEMBER_VERSIONED_DATASET,
        start_date=start_date,
        end_date=end_date,
        records=frame.height,
        duration_s=round(perf_counter() - started, 2),
        status=_SUCCESS_STATUS,
        updated=True,
    )


def _source_tasks_ready(
    plan: Sequence[SyncTaskItem],
    results: Sequence[SyncExecutionResult],
) -> bool:
    """仅在每个已计划的源任务都成功或已是最新时允许派生刷新。"""
    for task in plan:
        if task.status == _UP_TO_DATE_STATUS:
            continue
        if task.status != "PENDING":
            return False
        task_results = [result for result in results if result.endpoint == task.endpoint]
        if not task_results or any(result.status != _SUCCESS_STATUS for result in task_results):
            return False
    return True


def refresh_sw_2021_industry_golden(
    data_source: str,
    plan: Sequence[SyncTaskItem],
    results: Sequence[SyncExecutionResult],
    *,
    runtime: DataRuntimeContext | None = None,
) -> SyncExecutionResult | None:
    """在任一申万成员源更新后重建跨源行业黄金表。"""
    source = data_source.lower()
    source_tasks = _SW_INDUSTRY_GOLDEN_SOURCE_TASKS.get(source, frozenset())
    relevant_plan = [item for item in plan if item.endpoint in source_tasks]
    if not relevant_plan:
        return None
    successful_results = [
        result
        for result in results
        if result.endpoint in source_tasks and result.status == _SUCCESS_STATUS
    ]
    if not successful_results:
        return None

    start_date = min(result.start_date for result in successful_results)
    end_date = max(result.end_date for result in successful_results)
    if not _source_tasks_ready(relevant_plan, results):
        error = f"{SW_INDUSTRY_MEMBER_GOLDEN_DATASET} 自动重建被阻断：相关源表未全部成功或已是最新"
        logger.warning(error)
        return SyncExecutionResult(
            data_source="derived",
            endpoint=SW_INDUSTRY_MEMBER_GOLDEN_DATASET,
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=0.0,
            status="BLOCKED",
            error=error,
        )
    started = perf_counter()
    try:
        materialized = materialize_sw_2021_industry_golden(runtime=runtime, dry_run=False)
        if materialized.dimension.is_empty() or materialized.members.is_empty():
            logger.warning("申万跨源黄金表重建结果为空，保留旧表")
            return None
    except Exception as exc:
        error = f"自动重建 {SW_INDUSTRY_MEMBER_GOLDEN_DATASET} 失败: {exc}"
        logger.error(error)
        return SyncExecutionResult(
            data_source="derived",
            endpoint=SW_INDUSTRY_MEMBER_GOLDEN_DATASET,
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=round(perf_counter() - started, 2),
            status="FAILED",
            error=error,
        )

    logger.info(
        f"{source} 申万源表同步成功，自动重建 {SW_INDUSTRY_MEMBER_GOLDEN_DATASET} 完成 "
        f"[members={materialized.members.height}, dimension={materialized.dimension.height}]"
    )
    return SyncExecutionResult(
        data_source="derived",
        endpoint=SW_INDUSTRY_MEMBER_GOLDEN_DATASET,
        start_date=start_date,
        end_date=end_date,
        records=materialized.members.height,
        duration_s=round(perf_counter() - started, 2),
        status=_SUCCESS_STATUS,
        updated=True,
    )


def refresh_semiconductor_equipment_gm_multi(
    plan: Sequence[SyncTaskItem],
    results: Sequence[SyncExecutionResult],
    *,
    runtime: DataRuntimeContext | None = None,
) -> SyncExecutionResult | None:
    """在四家设备商原子表均就绪后原子重建跨公司 GM 表。"""
    relevant_plan = [item for item in plan if item.endpoint in _EQUIPMENT_GM_SOURCE_TASKS]
    if not relevant_plan:
        return None
    successful_results = [
        result
        for result in results
        if result.endpoint in _EQUIPMENT_GM_SOURCE_TASKS and result.status == _SUCCESS_STATUS
    ]
    if not successful_results and _equipment_source_tasks_ready(relevant_plan, results):
        curated_root = runtime.curated_root if runtime is not None else Path("data/curated")
        target = curated_root / "industry" / _EQUIPMENT_GM_TARGET
        if target.exists():
            return None
    start_date = (
        min(result.start_date for result in successful_results)
        if successful_results
        else min(item.start_date for item in relevant_plan)
    )
    end_date = (
        max(result.end_date for result in successful_results)
        if successful_results
        else max(item.end_date for item in relevant_plan)
    )
    if not _equipment_source_tasks_ready(relevant_plan, results):
        error = (
            "semiconductor_equipment_gm_multi 自动重建被阻断：四个公司级源任务未全部成功或已是最新"
        )
        logger.warning(error)
        return SyncExecutionResult(
            data_source="derived",
            endpoint="semiconductor_equipment_gm_multi",
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=0.0,
            status="BLOCKED",
            error=error,
        )

    started = perf_counter()
    try:
        curated_root = runtime.curated_root if runtime is not None else Path("data/curated")
        import polars as pl

        from stock_data.fetcher.industry.common import save_curated_fact
        from stock_data.fetcher.industry.semiconductor.schemas import (
            SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA,
        )

        atomic_files = {
            endpoint: curated_root / "industry" / "semiconductor/equipment" / f"{endpoint}.parquet"
            for endpoint in _EQUIPMENT_GM_COMPANIES
        }
        atomic_frames = [pl.read_parquet(path) for path in atomic_files.values() if path.exists()]
        if len(atomic_frames) != len(_EQUIPMENT_GM_SOURCE_TASKS):
            raise ValueError("四家设备商 GM 原子表不完整")
        projected: list[pl.DataFrame] = []
        for endpoint, atomic in zip(atomic_files, atomic_frames, strict=True):
            if endpoint == "tel_gm_quarterly":
                projected.append(
                    atomic.select(
                        ["company", "report_quarter", "release_date", "gross_margin_pct"]
                    ).with_columns(
                        pl.lit(None, dtype=pl.Float64).alias("gm_guidance_next_pct"),
                        pl.lit(None, dtype=pl.Float64).alias("services_share_pct"),
                        pl.lit("TEL_IR").alias("source"),
                        pl.lit("actual").alias("data_status"),
                    )
                )
            else:
                projected.append(
                    atomic.select(
                        [
                            "company",
                            "report_quarter",
                            "release_date",
                            "gross_margin_pct",
                            "gm_guidance_next_pct",
                            "services_share_pct",
                            "source",
                            "data_status",
                        ]
                    )
                )
        frame = (
            pl.concat(
                projected,
                how="diagonal_relaxed",
            )
            .cast(SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA)
            .unique(subset=["company", "report_quarter"], keep="last")
            .sort(["release_date", "company"])
        )
        if frame.is_empty():
            raise ValueError("四家设备商 GM 重建结果为空")
        target = curated_root / "industry" / _EQUIPMENT_GM_TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        save_curated_fact(frame, temporary, primary_keys=["company", "report_quarter"])
        temporary.replace(target)
    except Exception as exc:
        error = f"自动重建 semiconductor_equipment_gm_multi 失败: {exc}"
        logger.error(error)
        return SyncExecutionResult(
            data_source="derived",
            endpoint="semiconductor_equipment_gm_multi",
            start_date=start_date,
            end_date=end_date,
            records=0,
            duration_s=round(perf_counter() - started, 2),
            status="FAILED",
            error=error,
        )

    return SyncExecutionResult(
        data_source="derived",
        endpoint="semiconductor_equipment_gm_multi",
        start_date=start_date,
        end_date=end_date,
        records=frame.height,
        duration_s=round(perf_counter() - started, 2),
        status=_SUCCESS_STATUS,
        updated=True,
    )


def _equipment_source_tasks_ready(
    plan: Sequence[SyncTaskItem],
    results: Sequence[SyncExecutionResult],
) -> bool:
    """允许原子源任务以 SUCCESS/NO_CHANGE/UP_TO_DATE 进入派生重建。"""
    for task in plan:
        if task.status == _UP_TO_DATE_STATUS:
            continue
        task_results = [result for result in results if result.endpoint == task.endpoint]
        if not task_results or any(
            result.status not in {_SUCCESS_STATUS, "NO_CHANGE", _UP_TO_DATE_STATUS}
            for result in task_results
        ):
            return False
    return True


__all__ = [
    "refresh_semiconductor_equipment_gm_multi",
    "refresh_sw_2021_industry_golden",
    "refresh_tushare_index_member_versioned",
]
