"""CPCA 乘用车产销采集器。"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.automotive.clients.cpca import (
    CPCA_DATA_API_URL,
    CPCA_HEADERS,
    CPCA_OFFICIAL_BASE_URL,
    CPCA_REPORT_INDEX_URL,
    CpcaOnlineClient,
    requests,
)
from stock_data.fetcher.industry.automotive.lineage import file_lineage
from stock_data.fetcher.industry.automotive.merger import month_keys
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.parsers.cpca import (
    CPCA_BASE_URL,
    parse_cpca_bulletin_article,
    parse_cpca_snapshot,
)
from stock_data.fetcher.industry.automotive.paths import AutomotiveRawPaths
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    read_raw_text,
)

logger = logging.getLogger(__name__)


class CpcaBulletinCrawler:
    """扫描 CPCA 本地快照和官方月报归档。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = AutomotiveRawPaths(self.raw_dir)

    def fetch_latest_bulletins(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> dict[str, dict[str, Any]]:
        del force
        results: dict[str, dict[str, Any]] = {}
        for file_path in _snapshot_files(self.paths.cpca_dirs):
            content = read_raw_text(file_path)
            if not content:
                continue
            parsed_items = parse_cpca_snapshot(content, file_path)
            if not parsed_items:
                parsed = parse_cpca_bulletin_article(content, source_url=str(file_path))
                parsed_items = [parsed] if parsed else []
            for parsed in parsed_items:
                if parsed and _in_range(parsed["report_month"], start_date, end_date):
                    content_hash, snapshot_ref = file_lineage(file_path, self.raw_dir)
                    parsed["raw_content_sha256"] = parsed.get("raw_content_sha256") or content_hash
                    parsed["raw_snapshot_path"] = parsed.get("raw_snapshot_path") or snapshot_ref
                    results[parsed["report_month"]] = parsed
        return results


class CpcaCollector:
    """只负责 CPCA 源的乘用车产销、出口和渗透率。"""

    source = "CPCA"

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = AutomotiveRawPaths(self.raw_dir)
        self.cpca_dir = self.paths.cpca_dir
        self.crawler = CpcaBulletinCrawler(raw_dir=self.raw_dir)
        self.online = CpcaOnlineClient(self.raw_dir)
        self.last_errors: tuple[str, ...] = ()
        self.last_online_attempted = False
        self.last_fetched_periods: tuple[str, ...] = ()

    def collect(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> list[NevMonthlyRecord]:
        self.last_errors = ()
        self.last_online_attempted = False
        self.last_fetched_periods = ()
        bulletins = self.crawler.fetch_latest_bulletins(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        local_records = _records_from_infos(bulletins.values())
        cached_periods = {record.report_month for record in local_records}
        requested_periods = set(month_keys(start_date, end_date))
        target_periods = requested_periods or {_previous_month_key()}
        if not force and target_periods <= cached_periods:
            return local_records
        self.last_online_attempted = True
        online_records = self.fetch_online(start_date=start_date, end_date=end_date)
        if not online_records:
            self.last_errors = self.online.last_errors or ("CPCA 官方在线采集失败或返回空数据",)
            return local_records
        self.last_fetched_periods = tuple(
            sorted({record.report_month for record in online_records})
        )
        return _merge_records(local_records, online_records)

    def fetch_online(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NevMonthlyRecord]:
        """在线调用 CPCA 官方统计接口和月报归档。"""
        infos = self.online.fetch(start_date=start_date, end_date=end_date)
        self.last_errors = self.online.last_errors
        self.last_fetched_periods = self.online.last_fetched_periods
        return _records_from_infos(infos)

    def replay_cached_snapshots(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NevMonthlyRecord]:
        """仅解析本地 CPCA RAW 快照，不触发在线采集。"""
        bulletins = self.crawler.fetch_latest_bulletins(
            start_date=start_date,
            end_date=end_date,
        )
        return _records_from_infos(bulletins.values())


def _records_from_infos(infos: Any) -> list[NevMonthlyRecord]:
    records: list[NevMonthlyRecord] = []
    for info in infos:
        report_month = str(info["report_month"])
        year, month = parse_month_string(report_month)
        records.append(
            NevMonthlyRecord(
                report_month=report_month,
                trade_date=get_month_end_date(year, month),
                wholesale_volume_ten_thousand=info.get("wholesale_volume_ten_thousand"),
                total_volume_ten_thousand=info.get("total_volume_ten_thousand"),
                retail_volume_ten_thousand=info.get("retail_volume_ten_thousand"),
                export_volume_ten_thousand=info.get("export_volume_ten_thousand"),
                penetration_rate=info.get("penetration_rate"),
                unit="ten_thousand_units",
                source="CPCA",
                source_url=str(info.get("source_url") or f"{CPCA_BASE_URL}/"),
                release_date=info.get("release_date"),
                data_status="actual",
                collected_at=str(info.get("collected_at") or now_utc_iso()),
                wholesale_volume_raw=_optional_str(info.get("wholesale_volume_raw")),
                total_volume_raw=_optional_str(info.get("total_volume_raw")),
                retail_volume_raw=_optional_str(info.get("retail_volume_raw")),
                export_volume_raw=_optional_str(info.get("export_volume_raw")),
                penetration_rate_raw=_optional_str(info.get("penetration_rate_raw")),
                raw_content_sha256=str(info.get("raw_content_sha256") or ""),
                raw_snapshot_path=str(info.get("raw_snapshot_path") or ""),
            )
        )
    return sorted(records, key=lambda record: record.trade_date)


def _merge_records(
    local_records: list[NevMonthlyRecord], online_records: list[NevMonthlyRecord]
) -> list[NevMonthlyRecord]:
    merged = {record.report_month: record for record in local_records}
    for incoming in online_records:
        existing = merged.get(incoming.report_month)
        if existing is None:
            merged[incoming.report_month] = incoming
            continue
        merged[incoming.report_month] = replace(
            existing,
            wholesale_volume_ten_thousand=(
                incoming.wholesale_volume_ten_thousand or existing.wholesale_volume_ten_thousand
            ),
            total_volume_ten_thousand=incoming.total_volume_ten_thousand
            or existing.total_volume_ten_thousand,
            retail_volume_ten_thousand=incoming.retail_volume_ten_thousand
            or existing.retail_volume_ten_thousand,
            export_volume_ten_thousand=incoming.export_volume_ten_thousand
            or existing.export_volume_ten_thousand,
            penetration_rate=incoming.penetration_rate or existing.penetration_rate,
            source=incoming.source or existing.source,
            source_url=incoming.source_url or existing.source_url,
            release_date=incoming.release_date or existing.release_date,
            collected_at=incoming.collected_at or existing.collected_at,
            wholesale_volume_raw=incoming.wholesale_volume_raw or existing.wholesale_volume_raw,
            total_volume_raw=incoming.total_volume_raw or existing.total_volume_raw,
            retail_volume_raw=incoming.retail_volume_raw or existing.retail_volume_raw,
            export_volume_raw=incoming.export_volume_raw or existing.export_volume_raw,
            penetration_rate_raw=incoming.penetration_rate_raw or existing.penetration_rate_raw,
            raw_content_sha256=incoming.raw_content_sha256 or existing.raw_content_sha256,
            raw_snapshot_path=incoming.raw_snapshot_path or existing.raw_snapshot_path,
        )
    return sorted(merged.values(), key=lambda record: record.trade_date)


def _snapshot_files(directories: tuple[Path, ...]) -> list[Path]:
    files: dict[str, Path] = {}
    for directory in directories:
        for pattern in ("*.html", "*.html.gz", "*.txt", "*.txt.gz", "*.json", "*.json.gz"):
            for path in directory.glob(pattern):
                files[str(path)] = path
    return sorted(files.values())


def _in_range(report_month: str, start_date: date | None, end_date: date | None) -> bool:
    year, month = parse_month_string(report_month)
    return not (
        (start_date and get_month_end_date(year, month) < start_date)
        or (end_date and date(year, month, 1) > end_date)
    )


def _previous_month_key(today: date | None = None) -> str:
    current = today or date.today()
    if current.month == 1:
        return f"{current.year - 1:04d}-12"
    return f"{current.year:04d}-{current.month - 1:02d}"


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "CPCA_DATA_API_URL",
    "CPCA_HEADERS",
    "CPCA_OFFICIAL_BASE_URL",
    "CPCA_REPORT_INDEX_URL",
    "CpcaBulletinCrawler",
    "CpcaCollector",
    "CpcaOnlineClient",
    "requests",
]
