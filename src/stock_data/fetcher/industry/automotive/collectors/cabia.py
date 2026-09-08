"""CABIA 动力电池装车量采集器。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.automotive.clients.cabia import (
    CABIA_HEADERS,
    CABIA_ONLINE_BASE_URL,
    CABIA_RESOURCE_API_URL,
    CabiaOnlineClient,
    requests,
)
from stock_data.fetcher.industry.automotive.lineage import file_lineage
from stock_data.fetcher.industry.automotive.merger import month_keys
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.parsers.cabia import (
    parse_cabia_battery_article,
    parse_cabia_snapshot,
)
from stock_data.fetcher.industry.automotive.paths import AutomotiveRawPaths
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    read_raw_text,
)

CABIA_BASE_URL = "http://www.cabr-ac.com"


class CabiaCrawler:
    """发现 CABIA 公开月报并解析可验证的动力电池装车量。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        *,
        timeout: int = 15,
        impersonate: str = "chrome120",
        resource_api_url: str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = AutomotiveRawPaths(self.raw_dir)
        self.online = CabiaOnlineClient(
            self.raw_dir,
            timeout=timeout,
            impersonate=impersonate,
            resource_api_url=resource_api_url,
        )
        self.resource_api_url = self.online.resource_api_url
        self.last_errors: tuple[str, ...] = ()
        self.last_online_attempted = False
        self.last_fetched_periods: tuple[str, ...] = ()

    def fetch_latest_bulletins(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """扫描本地快照，按水位需要发现 CABIA 在线月报。"""
        self.paths.cabia_dir.mkdir(parents=True, exist_ok=True)
        self.last_errors = ()
        self.last_online_attempted = False
        self.last_fetched_periods = ()

        results = self._load_local_bulletins(start_date=start_date, end_date=end_date)
        requested_periods = set(month_keys(start_date, end_date))
        target_periods = requested_periods or {_previous_month_key()}
        should_fetch = force or not target_periods <= set(results)
        if not should_fetch:
            return results

        self.last_online_attempted = True
        online_results = self.online.fetch(
            start_date=start_date,
            end_date=end_date,
            max_pages=1 if not requested_periods else 12,
        )
        self.last_errors = self.online.last_errors
        self.last_fetched_periods = self.online.last_fetched_periods
        results.update(online_results)
        return results

    def replay_cached_bulletins(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, dict[str, Any]]:
        """仅读取本地 CABIA RAW 快照，不触发在线发现。"""
        return self._load_local_bulletins(start_date=start_date, end_date=end_date)

    def _load_local_bulletins(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for file_path in _snapshot_files(self.paths.cabia_dirs):
            content = read_raw_text(file_path)
            if not content:
                continue
            parsed_items = parse_cabia_snapshot(content, file_path)
            if not parsed_items:
                parsed = parse_cabia_battery_article(content, source_url=str(file_path))
                parsed_items = [parsed] if parsed else []
            for parsed in parsed_items:
                if parsed and _in_range(parsed["report_month"], start_date, end_date):
                    content_hash, snapshot_ref = file_lineage(file_path, self.raw_dir)
                    parsed["raw_content_sha256"] = parsed.get("raw_content_sha256") or content_hash
                    parsed["raw_snapshot_path"] = parsed.get("raw_snapshot_path") or snapshot_ref
                    results[parsed["report_month"]] = parsed
        return results


class CabiaCollector:
    """只负责 CABIA 源的动力电池月度指标。"""

    source = "CABIA"

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.crawler = CabiaCrawler(raw_dir=self.raw_dir)
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
        bulletins = self.crawler.fetch_latest_bulletins(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        self.last_errors = self.crawler.last_errors
        self.last_online_attempted = self.crawler.last_online_attempted
        self.last_fetched_periods = self.crawler.last_fetched_periods
        records: list[NevMonthlyRecord] = []
        for info in bulletins.values():
            report_month = str(info["report_month"])
            year, month = parse_month_string(report_month)
            records.append(
                NevMonthlyRecord(
                    report_month=report_month,
                    trade_date=get_month_end_date(year, month),
                    battery_installation_gwh=info.get("battery_installation_gwh"),
                    yoy_growth=info.get("yoy_growth"),
                    unit="gwh",
                    source=self.source,
                    source_url=str(info.get("source_url") or ""),
                    release_date=info.get("release_date"),
                    data_status="actual",
                    collected_at=str(info.get("collected_at") or now_utc_iso()),
                    battery_installation_gwh_raw=_optional_str(
                        info.get("battery_installation_gwh_raw")
                    ),
                    yoy_growth_raw=_optional_str(info.get("yoy_growth_raw")),
                    raw_content_sha256=str(info.get("raw_content_sha256") or ""),
                    raw_snapshot_path=str(info.get("raw_snapshot_path") or ""),
                )
            )
        return sorted(records, key=lambda record: record.trade_date)

    def replay_cached_snapshots(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NevMonthlyRecord]:
        """仅解析本地 CABIA RAW 快照，不触发在线采集。"""
        bulletins = self.crawler.replay_cached_bulletins(
            start_date=start_date,
            end_date=end_date,
        )
        return _records_from_infos(bulletins.values())


def _snapshot_files(directories: tuple[Path, ...]) -> list[Path]:
    files: dict[str, Path] = {}
    for directory in directories:
        for pattern in ("*.html", "*.html.gz", "*.txt", "*.txt.gz", "*.json", "*.json.gz"):
            for path in directory.glob(pattern):
                files[str(path)] = path
    return sorted(files.values())


def _in_range(report_month: str, start_date: date | None, end_date: date | None) -> bool:
    year, month = parse_month_string(report_month)
    month_start = date(year, month, 1)
    month_end = get_month_end_date(year, month)
    return not (
        (start_date is not None and month_end < start_date)
        or (end_date is not None and month_start > end_date)
    )


def _previous_month_key(today: date | None = None) -> str:
    current = today or date.today()
    if current.month == 1:
        return f"{current.year - 1:04d}-12"
    return f"{current.year:04d}-{current.month - 1:02d}"


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _records_from_infos(infos: Any) -> list[NevMonthlyRecord]:
    records: list[NevMonthlyRecord] = []
    for info in infos:
        report_month = str(info["report_month"])
        year, month = parse_month_string(report_month)
        records.append(
            NevMonthlyRecord(
                report_month=report_month,
                trade_date=get_month_end_date(year, month),
                battery_installation_gwh=info.get("battery_installation_gwh"),
                yoy_growth=info.get("yoy_growth"),
                unit="gwh",
                source="CABIA",
                source_url=str(info.get("source_url") or ""),
                release_date=info.get("release_date"),
                data_status="actual",
                collected_at=str(info.get("collected_at") or now_utc_iso()),
                battery_installation_gwh_raw=_optional_str(
                    info.get("battery_installation_gwh_raw")
                ),
                yoy_growth_raw=_optional_str(info.get("yoy_growth_raw")),
                raw_content_sha256=str(info.get("raw_content_sha256") or ""),
                raw_snapshot_path=str(info.get("raw_snapshot_path") or ""),
            )
        )
    return sorted(records, key=lambda record: record.trade_date)


__all__ = [
    "CABIA_BASE_URL",
    "CABIA_HEADERS",
    "CABIA_ONLINE_BASE_URL",
    "CABIA_RESOURCE_API_URL",
    "CabiaCollector",
    "CabiaCrawler",
    "requests",
]
