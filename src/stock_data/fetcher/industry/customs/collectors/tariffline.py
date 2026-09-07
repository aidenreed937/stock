"""UN Comtrade Tariffline 的小批量、可恢复原始采集。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.customs.collectors.tariffline_requests import (
    fetch_dataframe as _fetch_dataframe_impl,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_requests import (
    request_with_retry,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_storage import (
    append_manifest as _append_manifest,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_storage import (
    legacy_snapshot_path as _legacy_snapshot_path,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_storage import (
    snapshot_path as _snapshot_path,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_storage import (
    valid_snapshot as _valid_snapshot,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_storage import (
    write_snapshot as _write_snapshot,
)
from stock_data.fetcher.industry.customs.collectors.tariffline_types import (
    _MAX_RECORDS,
    TarifflineCallLimiter,
    TarifflineCallLimitError,
    TarifflineStatus,
)

logger = logging.getLogger(__name__)


def _normalize_flow_code(flow_code: str) -> str:
    """规范 Tariffline 贸易方向。"""
    codes = {part.strip().upper() for part in flow_code.split(",") if part.strip()}
    if not codes or not codes <= {"M", "X"}:
        raise ValueError(f"不支持的 Tariffline flow_code: {flow_code!r}")
    return ",".join(code for code in ("M", "X") if code in codes)


def _normalize_periods(period: str | Sequence[str]) -> list[str]:
    """规范并校验 Tariffline 月份列表。"""
    raw_periods = period.split(",") if isinstance(period, str) else list(period)
    periods: list[str] = []
    for raw_period in raw_periods:
        value = str(raw_period).strip().replace("-", "")
        if len(value) != 6 or not value.isdigit() or not 1 <= int(value[4:]) <= 12:
            raise ValueError(f"月份必须是 YYYY-MM 或 YYYYMM: {raw_period!r}")
        periods.append(value)
    if not periods:
        raise ValueError("Tariffline period 不能为空")
    return list(dict.fromkeys(periods))


def _normalize_cmd_codes(cmd_codes: Sequence[str]) -> list[str]:
    """规范 Tariffline 父级码/税则线列表。"""
    normalized: set[str] = set()
    for raw_code in cmd_codes:
        for part in str(raw_code).split(","):
            code = part.strip()
            if not code:
                continue
            if not code.isdigit() or not 1 <= len(code) <= 8:
                raise ValueError(f"不支持的 Tariffline cmdCode: {code!r}")
            normalized.add(code)
    return sorted(normalized)


def _month_range(start_month: str, end_month: str) -> list[str]:
    """生成闭区间月份列表。"""
    start = _normalize_periods(start_month)[0]
    end = _normalize_periods(end_month)[0]
    sy, sm = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    if (sy, sm) > (ey, em):
        raise ValueError(f"起始月份不能晚于结束月份: {start_month} > {end_month}")
    periods: list[str] = []
    year, month = sy, sm
    while (year, month) <= (ey, em):
        periods.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return periods


def _chunk_periods(periods: list[str], batch_months: int) -> list[list[str]]:
    """按小月份批次切分请求。"""
    if not 1 <= batch_months <= 12:
        raise ValueError("batch_months 必须在 1 到 12 之间")
    return [periods[index : index + batch_months] for index in range(0, len(periods), batch_months)]


def tariffline_snapshot_path(
    raw_dir: Path | str,
    periods: Sequence[str],
    flow_code: str,
    cmd_codes: Sequence[str],
    output_name: str | None = None,
) -> Path:
    """生成稳定的 Tariffline RAW 文件路径。"""
    del output_name
    return _snapshot_path(
        raw_dir,
        _normalize_periods(periods),
        _normalize_flow_code(flow_code),
        _normalize_cmd_codes(cmd_codes),
    )


def legacy_tariffline_snapshot_path(
    raw_dir: Path | str,
    periods: Sequence[str],
    flow_code: str,
    cmd_codes: Sequence[str],
    output_name: str | None = None,
) -> Path:
    """生成迁移前 Tariffline JSON.GZ 快照路径。"""
    return _legacy_snapshot_path(
        raw_dir,
        _normalize_periods(periods),
        _normalize_flow_code(flow_code),
        _normalize_cmd_codes(cmd_codes),
        output_name,
    )


def _fetch_tariffline_dataframe(**request_kwargs: Any) -> Any:
    """保留可 monkeypatch 的 Tariffline HTTP 入口。"""
    return _fetch_dataframe_impl(**request_kwargs)


def _request_with_retry(
    **kwargs: Any,
) -> tuple[TarifflineStatus, list[dict[str, Any]]]:
    """使用当前模块的 HTTP 入口执行请求与重试。"""
    return request_with_retry(fetcher=_fetch_tariffline_dataframe, **kwargs)


def fetch_tariffline_snapshot(
    *,
    subscription_key: str,
    raw_dir: Path | str,
    period: str | Sequence[str],
    flow_code: str,
    cmd_codes: Sequence[str],
    output_name: str | None = None,
    max_records: int = _MAX_RECORDS,
) -> list[dict[str, Any]]:
    """兼容旧 CLI 的 Tariffline 单次采集入口。"""
    if not subscription_key:
        logger.warning("未配置 COMTRADE_SUBSCRIPTION_KEY，无法拉取 Tariffline 数据")
        return []
    if not 1 <= max_records <= _MAX_RECORDS:
        raise ValueError(f"Tariffline max_records 必须在 1 到 {_MAX_RECORDS} 之间")

    periods = _normalize_periods(period)
    normalized_flow = _normalize_flow_code(flow_code)
    normalized_codes = _normalize_cmd_codes(cmd_codes)
    if not normalized_codes:
        logger.warning("Tariffline 查询码列表为空，取消请求")
        return []

    limiter = TarifflineCallLimiter()
    records: list[dict[str, Any]] = []
    for cmd_code in normalized_codes:
        try:
            status, batch_records = _request_with_retry(
                subscription_key=subscription_key,
                periods=periods,
                flow_code=normalized_flow,
                cmd_code=cmd_code,
                max_records=max_records,
                retries=1,
                retry_sleep_seconds=1.0,
                limiter=limiter,
            )
        except TarifflineCallLimitError as exc:
            logger.error("Tariffline 快照未写入: %s", exc)
            return []
        if status in {"failed", "truncated"}:
            logger.error(
                "Tariffline 快照未写入: status=%s, periods=%s, cmdCode=%s",
                status,
                ",".join(periods),
                cmd_code,
            )
            return []
        records.extend(batch_records)

    if not records:
        return []
    snapshot = tariffline_snapshot_path(
        raw_dir,
        periods,
        normalized_flow,
        normalized_codes,
        output_name=output_name,
    )
    _write_snapshot(snapshot, records)
    logger.info("Tariffline 快照写入: %s, records=%d", snapshot, len(records))
    return records


__all__ = [
    "_MAX_RECORDS",
    "TarifflineCallLimitError",
    "TarifflineCallLimiter",
    "TarifflineStatus",
    "_append_manifest",
    "_valid_snapshot",
    "_write_snapshot",
    "fetch_tariffline_snapshot",
    "legacy_tariffline_snapshot_path",
    "tariffline_snapshot_path",
]
