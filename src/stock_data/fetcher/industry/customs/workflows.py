"""Tariffline 历史回填编排：小批量、拆分、断点续拉。"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from stock_data.fetcher.industry.customs.collectors.tariffline import (
    _MAX_RECORDS,
    TarifflineCallLimiter,
    TarifflineCallLimitError,
    TarifflineStatus,
    _append_manifest,
    _chunk_periods,
    _month_range,
    _normalize_cmd_codes,
    _normalize_flow_code,
    _request_with_retry,
    _valid_snapshot,
    _write_snapshot,
    legacy_tariffline_snapshot_path,
    tariffline_snapshot_path,
)

logger = logging.getLogger(__name__)


@dataclass
class TarifflineBackfillSummary:
    """Tariffline 分批回填结果摘要。"""

    requested_batches: int = 0
    attempted_requests: int = 0
    completed_batches: int = 0
    skipped_batches: int = 0
    empty_batches: int = 0
    failed_batches: int = 0
    truncated_batches: int = 0
    split_batches: int = 0
    raw_files_written: int = 0
    api_calls_used: int = 0
    call_limit_reached: bool = False


def _chunk_codes(codes: list[str], batch_codes: int) -> list[list[str]]:
    if not 1 <= batch_codes <= 50:
        raise ValueError("batch_codes 必须在 1 到 50 之间")
    return [codes[index : index + batch_codes] for index in range(0, len(codes), batch_codes)]


def _snapshot_coverage(
    raw_dir: Path, periods: list[str], flow_code: str, cmd_codes: list[str]
) -> tuple[bool, int]:
    """识别完整或部分完成的拆分树，避免重跑父批次。"""
    output_name = f"{periods[0]}_{periods[-1]}"
    path = tariffline_snapshot_path(raw_dir, periods, flow_code, cmd_codes, output_name)
    legacy_path = legacy_tariffline_snapshot_path(
        raw_dir, periods, flow_code, cmd_codes, output_name
    )
    if _valid_snapshot(path) or _valid_snapshot(legacy_path):
        return True, 1
    if len(cmd_codes) > 1:
        midpoint = len(cmd_codes) // 2
        left = _snapshot_coverage(raw_dir, periods, flow_code, cmd_codes[:midpoint])
        right = _snapshot_coverage(raw_dir, periods, flow_code, cmd_codes[midpoint:])
    elif len(periods) > 1:
        midpoint = len(periods) // 2
        left = _snapshot_coverage(raw_dir, periods[:midpoint], flow_code, cmd_codes)
        right = _snapshot_coverage(raw_dir, periods[midpoint:], flow_code, cmd_codes)
    else:
        return False, 0
    return left[0] and right[0], left[1] + right[1]


def backfill_tariffline(
    *,
    subscription_key: str,
    raw_dir: Path | str,
    cmd_codes: Sequence[str],
    start_month: str,
    end_month: str,
    flow_code: str = "M,X",
    batch_months: int = 12,
    batch_codes: int = 5,
    max_records: int = _MAX_RECORDS,
    retries: int = 2,
    retry_sleep_seconds: float = 1.0,
    request_sleep_seconds: float = 0.2,
    force: bool = False,
    isolate_requests: bool = True,
    workers: int = 1,
) -> TarifflineBackfillSummary:
    """按 HS6 父码和月份小批量回填 Tariffline，逐批落盘并可断点续拉。"""
    if not subscription_key:
        raise ValueError("未配置 COMTRADE_SUBSCRIPTION_KEY")
    if retries < 0 or request_sleep_seconds < 0 or retry_sleep_seconds < 0:
        raise ValueError("重试次数和等待时间不能为负数")
    if not 1 <= workers <= 8:
        raise ValueError("workers 必须在 1 到 8 之间")
    if not 1 <= max_records <= _MAX_RECORDS:
        raise ValueError(f"Tariffline max_records 必须在 1 到 {_MAX_RECORDS} 之间")

    normalized_codes = _normalize_cmd_codes(cmd_codes)
    if not normalized_codes:
        raise ValueError("Tariffline cmd_codes 不能为空")
    periods = _month_range(start_month, end_month)
    normalized_flow = _normalize_flow_code(flow_code)
    initial_chunks = _chunk_periods(periods, batch_months)
    code_batches = _chunk_codes(normalized_codes, batch_codes)
    summary = TarifflineBackfillSummary(requested_batches=len(code_batches) * len(initial_chunks))
    root = Path(raw_dir)
    root.mkdir(parents=True, exist_ok=True)
    limiter = TarifflineCallLimiter()

    queue: deque[tuple[list[str], list[str]]] = deque(
        (period_chunk, code_batch) for code_batch in code_batches for period_chunk in initial_chunks
    )

    def split_task(period_chunk: list[str], cmd_batch: list[str]) -> None:
        midpoint = len(cmd_batch) // 2 if len(cmd_batch) > 1 else len(period_chunk) // 2
        if len(cmd_batch) > 1:
            queue.append((period_chunk, cmd_batch[:midpoint]))
            queue.append((period_chunk, cmd_batch[midpoint:]))
        else:
            queue.append((period_chunk[:midpoint], cmd_batch))
            queue.append((period_chunk[midpoint:], cmd_batch))
        summary.split_batches += 1

    def prepare_task(
        period_chunk: list[str], cmd_batch: list[str]
    ) -> tuple[list[str], list[str], Path] | None:
        output_name = f"{period_chunk[0]}_{period_chunk[-1]}"
        snapshot_path = tariffline_snapshot_path(
            root,
            period_chunk,
            normalized_flow,
            cmd_batch,
            output_name=output_name,
        )
        if not force:
            fully_covered, covered_batches = _snapshot_coverage(
                root, period_chunk, normalized_flow, cmd_batch
            )
            if fully_covered:
                summary.skipped_batches += covered_batches
                return None
            if covered_batches and (len(cmd_batch) > 1 or len(period_chunk) > 1):
                split_task(period_chunk, cmd_batch)
                return None
        if not force and snapshot_path.exists() and _valid_snapshot(snapshot_path):
            summary.skipped_batches += 1
            return None
        return period_chunk, cmd_batch, snapshot_path

    def request_task(
        task: tuple[list[str], list[str], Path],
    ) -> tuple[tuple[list[str], list[str], Path], TarifflineStatus, list[dict[str, object]]]:
        period_chunk, cmd_batch, _snapshot_path = task
        try:
            status, records = _request_with_retry(
                subscription_key=subscription_key,
                periods=period_chunk,
                flow_code=normalized_flow,
                cmd_code=",".join(cmd_batch),
                max_records=max_records,
                retries=retries,
                retry_sleep_seconds=retry_sleep_seconds,
                isolate=isolate_requests,
                limiter=limiter,
            )
        except TarifflineCallLimitError as exc:
            logger.error(
                "Tariffline API 调用预算耗尽: periods=%s, cmdCode=%s, error=%s",
                ",".join(period_chunk),
                ",".join(cmd_batch),
                exc,
            )
            return task, "quota_exhausted", []
        except Exception as exc:  # noqa: BLE001
            status, records = "failed", []
            logger.warning(
                "Tariffline 并行请求异常: periods=%s, cmdCode=%s, error=%s",
                ",".join(period_chunk),
                ",".join(cmd_batch),
                exc,
            )
        return task, status, records

    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        while queue:
            ready: list[tuple[list[str], list[str], Path]] = []
            while queue and len(ready) < workers:
                candidate = prepare_task(*queue.popleft())
                if candidate is not None:
                    ready.append(candidate)
            if not ready:
                continue

            summary.attempted_requests += len(ready)
            if executor is None:
                results = [request_task(task) for task in ready]
            else:
                futures = {executor.submit(request_task, task): task for task in ready}
                results = []
                for future in as_completed(futures):
                    results.append(future.result())

            budget_exhausted = False
            for task, status, records in results:
                period_chunk, cmd_batch, snapshot_path = task
                if status == "quota_exhausted":
                    summary.call_limit_reached = True
                    budget_exhausted = True
                    _append_manifest(
                        root,
                        periods=period_chunk,
                        flow_code=normalized_flow,
                        cmd_code=",".join(cmd_batch),
                        status=status,
                        rows=0,
                        snapshot_path=None,
                    )
                    continue
                if status == "truncated" and (len(period_chunk) > 1 or len(cmd_batch) > 1):
                    split_task(period_chunk, cmd_batch)
                    continue

                _append_manifest(
                    root,
                    periods=period_chunk,
                    flow_code=normalized_flow,
                    cmd_code=",".join(cmd_batch),
                    status=status,
                    rows=len(records),
                    snapshot_path=snapshot_path if status in {"success", "empty"} else None,
                )
                if status in {"success", "empty"}:
                    _write_snapshot(snapshot_path, records)
                    summary.completed_batches += 1
                    summary.raw_files_written += 1
                    if status == "empty":
                        summary.empty_batches += 1
                elif status == "truncated":
                    summary.truncated_batches += 1
                else:
                    summary.failed_batches += 1

            if budget_exhausted:
                break
            if request_sleep_seconds > 0 and queue:
                time.sleep(request_sleep_seconds)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    summary.api_calls_used = limiter.calls
    return summary


__all__ = ["TarifflineBackfillSummary", "backfill_tariffline"]
