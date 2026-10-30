"""CPCA 官方统计接口在线客户端。"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from curl_cffi import requests

from stock_data.fetcher.industry.automotive.clients.cpca_archive import (
    CPCA_HEADERS,
    CPCA_OFFICIAL_BASE_URL,
    CPCA_REPORT_INDEX_URL,
    CpcaReportArchiveClient,
)
from stock_data.fetcher.industry.automotive.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)

logger = logging.getLogger(__name__)

CPCA_DATA_API_URL = "http://data.cpcadata.com/api/chartlist"
_CPCA_MAX_ATTEMPTS = 2
_CPCA_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class CpcaOnlineClient:
    """调用 CPCA 官方当前统计接口，并按需委托历史月报归档。"""

    def __init__(
        self,
        raw_dir: Path,
        *,
        timeout: int = 60,
        impersonate: str = "chrome120",
        max_history_pages: int = 12,
        report_index_url: str = CPCA_REPORT_INDEX_URL,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.timeout = timeout
        self.impersonate = impersonate
        self.archive = CpcaReportArchiveClient(
            self.raw_dir,
            timeout=timeout,
            impersonate=impersonate,
            max_history_pages=max_history_pages,
            report_index_url=report_index_url,
        )
        self.last_errors: tuple[str, ...] = ()
        self.last_fetched_periods: tuple[str, ...] = ()

    def fetch(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        self.last_errors = ()
        self.last_fetched_periods = ()
        records = self._fetch_chart_records()
        requested = _month_keys(start_date, end_date)
        current_months = {str(record["report_month"]) for record in records}
        if requested and (requested - current_months):
            records.extend(self.archive.fetch(start_date=start_date, end_date=end_date))
            self.last_errors = (*self.last_errors, *self.archive.last_errors)
        deduped = {str(record["report_month"]): record for record in records}
        result = [
            record
            for month, record in sorted(deduped.items())
            if _month_in_range(month, start_date, end_date)
        ]
        self.last_fetched_periods = tuple(sorted(record["report_month"] for record in result))
        if not result and (start_date or end_date):
            self.last_errors = (
                *self.last_errors,
                "CPCA 官方接口与月报归档均未覆盖请求月份",
            )
        return result

    def _fetch_chart_records(self) -> list[dict[str, Any]]:
        payloads: dict[str, Any] = {}
        raw_parts: list[bytes] = []
        refs: list[str] = []
        for chart_type in ("6", "1"):
            url = f"{CPCA_DATA_API_URL}?{urlencode({'charttype': chart_type})}"
            response = None
            last_error: Exception | None = None
            for attempt in range(_CPCA_MAX_ATTEMPTS):
                try:
                    candidate = requests.get(
                        url,
                        headers=CPCA_HEADERS,
                        timeout=self.timeout,
                        impersonate=self.impersonate,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt + 1 < _CPCA_MAX_ATTEMPTS:
                        logger.debug("CPCA 官方统计接口暂时失败，准备重试 [%s]", chart_type)
                        continue
                    self._add_error(f"CPCA 官方统计接口请求失败 [{chart_type}]: {exc}")
                    break
                status_code = getattr(candidate, "status_code", 0)
                if status_code == 200:
                    response = candidate
                    break
                if status_code not in _CPCA_RETRY_STATUS_CODES or attempt + 1 >= _CPCA_MAX_ATTEMPTS:
                    self._add_error(f"CPCA 官方统计接口 HTTP {status_code} [{chart_type}]")
                    break
                logger.debug(
                    "CPCA 官方统计接口暂时返回 HTTP %s，准备重试 [%s]",
                    status_code,
                    chart_type,
                )
            if response is None:
                if last_error is not None:
                    logger.debug("CPCA 官方统计接口最终失败 [%s]: %s", chart_type, last_error)
                continue
            content = _response_bytes(response)
            if not content:
                self._add_error(f"CPCA 官方统计接口返回空响应 [{chart_type}]")
                continue
            payload = _json_payload(response, content)
            if not isinstance(payload, list) or not payload:
                self._add_error(f"CPCA 官方统计接口响应结构异常 [{chart_type}]")
                continue
            payloads[chart_type] = payload
            raw_parts.append(content)
            snapshot = save_raw_snapshot(
                "automotive",
                f"cpca/chartlist_{chart_type}.json",
                content,
                base_dir=self.raw_dir,
                compress=True,
            )
            refs.append(raw_snapshot_path_value(snapshot, self.raw_dir))

        if "6" not in payloads or "1" not in payloads:
            return []
        fuel_map = _chart_value_map(_chart_rows(payloads["6"]), 2)
        wholesale_map = _chart_value_map(_chart_rows(payloads["1"]), 1)
        retail_map = _chart_value_map(_chart_rows(payloads["1"]), 2)
        export_map = _chart_value_map(_chart_rows(payloads["1"]), 3)
        digest = raw_content_sha256(b"\n".join(raw_parts))
        snapshot_ref = ";".join(refs)
        collected_at = now_utc_iso()
        records: list[dict[str, Any]] = []
        for report_month in sorted(fuel_map):
            wholesale, wholesale_raw = fuel_map[report_month]
            total_item = wholesale_map.get(report_month)
            retail_item = retail_map.get(report_month)
            export_item = export_map.get(report_month)
            total = total_item[0] if total_item else None
            year, month = parse_month_string(report_month)
            penetration = round(wholesale / total, 4) if total and total > 0 else None
            records.append(
                {
                    "report_month": report_month,
                    "trade_date": get_month_end_date(year, month),
                    "wholesale_volume_ten_thousand": wholesale,
                    "total_volume_ten_thousand": total,
                    "retail_volume_ten_thousand": retail_item[0] if retail_item else None,
                    "export_volume_ten_thousand": export_item[0] if export_item else None,
                    "penetration_rate": penetration,
                    "unit": "ten_thousand_units",
                    "source": "CPCA",
                    "source_url": CPCA_DATA_API_URL,
                    "release_date": _next_month_tenth(year, month),
                    "data_status": "actual",
                    "collected_at": collected_at,
                    "wholesale_volume_raw": wholesale_raw,
                    "total_volume_raw": total_item[1] if total_item else None,
                    "retail_volume_raw": retail_item[1] if retail_item else None,
                    "export_volume_raw": export_item[1] if export_item else None,
                    "penetration_rate_raw": str(penetration) if penetration is not None else None,
                    "raw_content_sha256": digest,
                    "raw_snapshot_path": snapshot_ref,
                }
            )
        return records

    def _add_error(self, message: str) -> None:
        self.last_errors = (*self.last_errors, message)
        logger.warning(message)


def _chart_rows(payload: list[Any]) -> list[dict[str, Any]]:
    first = payload[0] if payload and isinstance(payload[0], dict) else {}
    rows = first.get("dataList", []) if isinstance(first, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _chart_value_map(rows: list[dict[str, Any]], index: int) -> dict[str, tuple[float, str]]:
    values: dict[str, tuple[float, str]] = {}
    for row in rows:
        month_raw = str(row.get("month", row.get("月份", ""))).replace("月", "").strip()
        try:
            month = int(month_raw)
        except ValueError:
            continue
        for key, raw_value in row.items():
            match = re.fullmatch(r"(20\d{2})年", str(key))
            if not match or not isinstance(raw_value, list) or len(raw_value) <= index:
                continue
            try:
                number = float(raw_value[index])
            except (TypeError, ValueError):
                continue
            if number > 0:
                values[f"{int(match.group(1)):04d}-{month:02d}"] = (number, str(raw_value[index]))
    return values


def _month_in_range(value: str, start_date: date | None, end_date: date | None) -> bool:
    year, month = parse_month_string(value)
    month_start = date(year, month, 1)
    month_end = get_month_end_date(year, month)
    return not (
        (start_date is not None and month_end < start_date)
        or (end_date is not None and month_start > end_date)
    )


def _month_keys(start_date: date | None, end_date: date | None) -> set[str]:
    if start_date is None and end_date is None:
        return set()
    cursor = (start_date or end_date).replace(day=1)  # type: ignore[union-attr]
    end = (end_date or start_date).replace(day=1)  # type: ignore[union-attr]
    result: set[str] = set()
    while cursor <= end:
        result.add(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def _next_month_tenth(year: int, month: int) -> date:
    return date(year + 1, 1, 10) if month == 12 else date(year, month + 1, 10)


def _response_bytes(response: Any) -> bytes:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        return content
    text = getattr(response, "text", "")
    return text.encode("utf-8") if isinstance(text, str) else b""


def _json_payload(response: Any, content: bytes) -> Any:
    try:
        return response.json()
    except (AttributeError, TypeError, ValueError):
        try:
            return json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}


def _month_start(value: str) -> date:
    year, month = parse_month_string(value)
    return date(year, month, 1)


__all__ = [
    "CPCA_DATA_API_URL",
    "CPCA_HEADERS",
    "CPCA_OFFICIAL_BASE_URL",
    "CPCA_REPORT_INDEX_URL",
    "CpcaOnlineClient",
    "CpcaReportArchiveClient",
    "requests",
]
