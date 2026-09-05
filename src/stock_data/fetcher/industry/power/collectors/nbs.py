"""国家统计局 (NBS) 太阳能电池月度产量采集器。"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.contracts import IndustryCollectionResult, as_collection_result
from stock_data.fetcher.industry.power.lineage import (
    file_lineage,
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.power.models import SolarCellNbsRecord
from stock_data.fetcher.industry.power.parsers.nbs import (
    parse_nbs_solar_cell_response_rows,
)
from stock_data.fetcher.industry.power.paths import PowerRawPaths
from stock_data.fetcher.industry.power.transforms.facts import records_to_raw_solar_cell_nbs_frame

logger = logging.getLogger(__name__)

NBS_EXTERNAL_QUERY_URL = "https://data.stats.gov.cn/dg/website/publicrelease/web/external/query"
NBS_STREAM_DATA_URL = (
    "https://data.stats.gov.cn/dg/website/publicrelease/web/external/stream/esData"
)
NBS_SOLAR_CELL_CID = "b26bbe4fca814e9197de24852d2011d5"
NBS_SOLAR_CELL_ROOT_ID = "fc982599aa684be7969d7b90b1bd0e84"
NBS_SOLAR_CELL_INDICATOR_IDS = (
    "97951619231f4be6bee905d904d30bc2",
    "3c643cafa6c8430f9e609521eae4b7d0",
    "851109fcaaf348cd8b2989bbc8dba2f6",
    "a60ac50ecacd49b0a65482ab335d430c",
)
NBS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://data.stats.gov.cn",
    "Referer": "https://data.stats.gov.cn/dg/website/page.html#/pc/national/monthData",
}


def _safe_float(value: object) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip().replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _infer_nbs_data_status(raw_values: dict[str, str | None]) -> str:
    """主字段全部缺失视为未披露占位行，与硅业分会 `missing_unverified` 口径一致。"""
    if all(not (value and str(value).strip()) for value in raw_values.values()):
        return "missing_unverified"
    return "actual"


def _month_keys(start_date: date | None, end_date: date | None) -> list[str]:
    """生成包含边界月份的 YYYY-MM 列表。"""
    if start_date is None and end_date is None:
        current_month = date.today().replace(day=1)
        latest_month = current_month - timedelta(days=1)
        if date.today().day < NbsSolarCellCollector.NBS_RELEASE_DAY:
            latest_month = latest_month.replace(day=1) - timedelta(days=1)
        return [latest_month.strftime("%Y-%m")]
    start = (start_date or date.today()).replace(day=1)
    end = (end_date or start_date or date.today()).replace(day=1)
    if end < start:
        return []
    result: list[str] = []
    cursor = start
    while cursor <= end:
        result.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


class NbsSolarCellCrawler:
    """国家统计局公开月度接口在线采集器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 20,
    ) -> None:
        self.paths = PowerRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.snapshot_dir = self.paths.nbs_dir / "snapshots"
        self.timeout = timeout

    def fetch_range(
        self,
        periods: list[str],
        *,
        force: bool = False,
    ) -> IndustryCollectionResult:
        """按报告月份请求 NBS 官方数据并逐月保存响应快照。"""
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        for period in periods:
            try:
                payload = {
                    "cid": NBS_SOLAR_CELL_CID,
                    "indicatorIds": list(NBS_SOLAR_CELL_INDICATOR_IDS),
                    "daCatalogId": "",
                    "das": [{"text": "全国", "value": "000000000000"}],
                    "showType": "1",
                    "rootId": NBS_SOLAR_CELL_ROOT_ID,
                    "dts": [period.replace("-", "") + "MM"],
                }
                response = requests.post(
                    NBS_STREAM_DATA_URL,
                    json=payload,
                    headers=NBS_HEADERS,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    errors.append(f"{period}: HTTP {response.status_code}")
                    continue
                content = getattr(response, "content", b"")
                if not isinstance(content, bytes) or not content:
                    content = str(getattr(response, "text", "")).encode("utf-8")
                try:
                    response_payload = cast("dict[str, Any]", json.loads(content.decode("utf-8")))
                except (ValueError, json.JSONDecodeError):
                    response_json = cast("Callable[[], object]", response.json)
                    response_payload = cast("dict[str, Any]", response_json())
                source_url = f"{NBS_STREAM_DATA_URL} (period={period})"
                parsed = next(
                    (
                        row
                        for row in parse_nbs_solar_cell_response_rows(
                            response_payload,
                            source_url=source_url,
                        )
                        if row.get("report_month") == period
                    ),
                    None,
                )
                if parsed is None:
                    errors.append(f"{period}: 未找到太阳能电池指标")
                    continue
                snapshot_path = save_raw_snapshot(
                    "power",
                    f"nbs/nbs_solar_cell_{period}.json.gz",
                    content,
                    base_dir=self.raw_root,
                    compress=True,
                )
                records.append(
                    {
                        **parsed,
                        "raw_content_sha256": raw_content_sha256(content),
                        "raw_snapshot_path": raw_snapshot_path_value(snapshot_path, self.raw_root),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{period}: {exc}")

        status = "SUCCESS" if not errors else ("PARTIAL" if records else "FAILED")
        return IndustryCollectionResult(
            records,
            status=status,
            fetched_periods=[str(row["report_month"]) for row in records],
            missing_periods=[
                period
                for period in periods
                if period not in {row["report_month"] for row in records}
            ],
            errors=errors,
            updated=bool(records),
        )


class NbsSolarCellCollector:
    """国家统计局 (NBS) 太阳能电池 (光伏电池) 月度产量采集适配器。

    读取已落盘 RAW CSV (`data/raw/industry/power/nbs/nbs_solar_cell_monthly.csv`)，
    结构对齐化工 NBS (report_month/output_current/output_cumulative/output_yoy/output_cum_yoy)。
    """

    NBS_RELEASE_DAY = 18

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        crawler: NbsSolarCellCrawler | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.csv_file = self.paths.solar_cell_nbs_csv
        self.crawler = crawler or NbsSolarCellCrawler(raw_dir=self.raw_dir)

    def _release_date(self, report_month: str) -> date:
        """兼容旧版 NBS 快照缺失发布日期时的月报发布日期口径。"""
        year, month = parse_month_string(report_month)
        if month == 12:
            return date(year + 1, 1, self.NBS_RELEASE_DAY)
        return date(year, month + 1, self.NBS_RELEASE_DAY)

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """智能读取本地覆盖并在线补齐缺口；显式 force 只刷新指定范围。"""
        existing_records = self.load_from_raw_csv(self.csv_file)
        existing_by_month = {record.report_month: record for record in existing_records}
        periods = _month_keys(start_date, end_date)
        if not periods:
            return IndustryCollectionResult(existing_records, status="EMPTY")

        covered = set(existing_by_month)
        to_fetch = periods if force else [period for period in periods if period not in covered]
        online_result = (
            as_collection_result(self.crawler.fetch_range(to_fetch, force=force))
            if to_fetch
            else IndustryCollectionResult([], status="SUCCESS")
        )
        online_records = self._records_from_online(online_result.records)
        before_values = {
            key: self._record_signature(value) for key, value in existing_by_month.items()
        }
        for record in online_records:
            existing_by_month[record.report_month] = record

        final_records = sorted(existing_by_month.values(), key=lambda record: record.trade_date)
        if final_records and (online_records or not self.csv_file.exists()):
            self.save_to_raw_csv(self.paths.nbs_dir / "nbs_solar_cell_monthly.csv", final_records)

        fetched = {record.report_month for record in online_records}
        missing = [
            period
            for period in periods
            if (period not in fetched if force else period not in existing_by_month)
        ]
        errors = list(online_result.errors)
        status = online_result.status if errors or missing else "SUCCESS"
        if status == "SUCCESS" and not fetched:
            status = "NO_CHANGE"
        updated = any(
            self._record_signature(existing_by_month[month]) != before_values.get(month)
            for month in fetched
        )
        return IndustryCollectionResult(
            final_records,
            status=status,
            fetched_periods=sorted(fetched),
            cached_periods=sorted(set(periods) & covered),
            missing_periods=missing,
            errors=errors,
            updated=updated,
        )

    @staticmethod
    def _record_signature(record: SolarCellNbsRecord) -> tuple[Any, ...]:
        return (
            record.output_current_raw,
            record.output_cumulative_raw,
            record.output_yoy_raw,
            record.output_cum_yoy_raw,
            record.raw_content_sha256,
        )

    def _records_from_online(self, rows: list[Any]) -> list[SolarCellNbsRecord]:
        records: list[SolarCellNbsRecord] = []
        for row in rows:
            if isinstance(row, SolarCellNbsRecord):
                records.append(row)
                continue
            if not isinstance(row, dict) or not row.get("report_month"):
                continue
            period = str(row["report_month"])
            year, month = parse_month_string(period)
            raw_values = {
                key: (str(row[key]) if row.get(key) is not None else None)
                for key in (
                    "output_current",
                    "output_cumulative",
                    "output_yoy",
                    "output_cum_yoy",
                )
            }
            records.append(
                SolarCellNbsRecord(
                    report_month=period,
                    trade_date=get_month_end_date(year, month),
                    output_current=_safe_float(raw_values["output_current"]),
                    output_cumulative=_safe_float(raw_values["output_cumulative"]),
                    output_yoy=_safe_float(raw_values["output_yoy"]),
                    output_cum_yoy=_safe_float(raw_values["output_cum_yoy"]),
                    unit=str(row.get("unit") or "ten_thousand_kw"),
                    source=str(row.get("source") or "NBS"),
                    source_url=str(row.get("source_url") or NBS_EXTERNAL_QUERY_URL),
                    release_date=self._release_date(period),
                    data_status=_infer_nbs_data_status(raw_values),
                    collected_at=now_utc_iso(),
                    output_current_raw=raw_values["output_current"],
                    output_cumulative_raw=raw_values["output_cumulative"],
                    output_yoy_raw=raw_values["output_yoy"],
                    output_cum_yoy_raw=raw_values["output_cum_yoy"],
                    raw_content_sha256=str(row.get("raw_content_sha256") or ""),
                    raw_snapshot_path=str(row.get("raw_snapshot_path") or ""),
                )
            )
        return records

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarCellNbsRecord]:
        """从 NBS RAW CSV 中读取并标准化记录。"""
        p = Path(file_path)
        if not p.exists():
            return []

        content_hash, snapshot_ref = file_lineage(p, self.raw_dir)
        records: list[SolarCellNbsRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                m_str = row["report_month"].strip()
                year, month = parse_month_string(m_str)
                release_date = None
                if row.get("release_date"):
                    try:
                        release_date = date.fromisoformat(row["release_date"].strip())
                    except ValueError:
                        release_date = None
                raw_values = {
                    key: row.get(f"{key}_raw") or row.get(key) or None
                    for key in (
                        "output_current",
                        "output_cumulative",
                        "output_yoy",
                        "output_cum_yoy",
                    )
                }
                records.append(
                    SolarCellNbsRecord(
                        report_month=m_str,
                        trade_date=get_month_end_date(year, month),
                        output_current=_safe_float(raw_values["output_current"]),
                        output_cumulative=_safe_float(raw_values["output_cumulative"]),
                        output_yoy=_safe_float(raw_values["output_yoy"]),
                        output_cum_yoy=_safe_float(raw_values["output_cum_yoy"]),
                        unit=row.get("unit") or "ten_thousand_kw",
                        source=row.get("source") or "NBS",
                        source_url=row.get("source_url") or "https://data.stats.gov.cn/",
                        release_date=release_date or self._release_date(m_str),
                        data_status=row.get("data_status") or _infer_nbs_data_status(raw_values),
                        collected_at=row.get("collected_at") or now_utc_iso(),
                        output_current_raw=raw_values["output_current"],
                        output_cumulative_raw=raw_values["output_cumulative"],
                        output_yoy_raw=raw_values["output_yoy"],
                        output_cum_yoy_raw=raw_values["output_cum_yoy"],
                        raw_content_sha256=row.get("raw_content_sha256") or content_hash,
                        raw_snapshot_path=row.get("raw_snapshot_path") or snapshot_ref,
                    )
                )
        records.sort(key=lambda record: record.trade_date)
        logger.info("已读取 NBS 太阳能电池产量 %d 个月 (RAW: %s)", len(records), p)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[SolarCellNbsRecord]) -> None:
        """持久化 NBS 源字段 RAW CSV 快照。"""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        records_to_raw_solar_cell_nbs_frame(records).write_csv(target)


__all__ = [
    "NBS_EXTERNAL_QUERY_URL",
    "NBS_HEADERS",
    "NBS_SOLAR_CELL_CID",
    "NBS_SOLAR_CELL_INDICATOR_IDS",
    "NBS_SOLAR_CELL_ROOT_ID",
    "NBS_STREAM_DATA_URL",
    "NbsSolarCellCollector",
    "NbsSolarCellCrawler",
]
