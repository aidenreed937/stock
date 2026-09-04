"""SEAJ (日本半导体设备制造协会) 月度半导体设备出货额采集器。

数据源: https://www.seaj.or.jp/statistics/
历史 Excel 提供日本制半导体设备销售 3MMA 底表，最新速报 PDF 用于覆盖近期月份。
采集器只保留源端数值、原文字符串和血缘信息；缺失 MoM/3MMA 派生值由 Curated 转换器计算。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorEquipmentRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    SeajPdfParser,
    parse_seaj_historical_xls,
    parse_seaj_historical_xls_url,
    parse_seaj_press_release_target,
    parse_seaj_release_calendar_pdf,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

SEAJ_BASE_URL = "https://www.seaj.or.jp/statistics/"
SEAJ_STATISTICS_URL = SEAJ_BASE_URL
SEAJ_RELEASE_DATES_URL = "https://www.seaj.or.jp/file/ReleaseDates.pdf"
SEAJ_SOURCE_NAME = "seaj"
SEAJ_INDEX_FILENAME = "seaj_statistics_index.html.gz"
SEAJ_HISTORICAL_XLS_FILENAME = "seaj_historical_billings.xls"
SEAJ_RELEASE_DATES_FILENAME = "release_dates.pdf"
SEAJ_LATEST_PDF_FILENAME = "latest_press_release.pdf"
START_YEAR = 2015

SEAJ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class SeajEquipmentCollector:
    """日本半导体设备制造协会 (SEAJ) 月度设备出货额采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 20,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.snapshot_dir = self.paths.seaj_dir
        self.timeout = timeout
        self.impersonate = impersonate
        self.pdf_parser = SeajPdfParser()

    def collect(self) -> list[SemiconductorEquipmentRecord]:
        """在线重建 SEAJ 月度设备出货原始记录。"""
        self.paths.semiconductor_dir.mkdir(parents=True, exist_ok=True)

        index_response = self._get(SEAJ_BASE_URL)
        if index_response is None:
            return []
        index_bytes = response_content_bytes(index_response)
        if not index_bytes:
            logger.warning("SEAJ statistics 首页响应为空")
            return []

        save_raw_snapshot(
            SEAJ_SOURCE_NAME,
            SEAJ_INDEX_FILENAME,
            index_bytes,
            base_dir=self.paths.semiconductor_dir,
            compress=True,
        )
        html_text = index_bytes.decode("shift_jis", errors="ignore")
        target = parse_seaj_press_release_target(html_text, base_url=SEAJ_BASE_URL)
        historical_url = parse_seaj_historical_xls_url(html_text, base_url=SEAJ_BASE_URL)
        release_dates = self._fetch_release_dates()
        collected_at = now_utc_iso()

        records = self._collect_historical(
            historical_url,
            release_dates=release_dates,
            collected_at=collected_at,
        )
        records.extend(
            self._collect_latest_pdf(
                target.pdf_url,
                target.release_date,
                release_dates=release_dates,
                collected_at=collected_at,
            )
        )

        deduped = {record.report_month: record for record in records}
        result = sorted(deduped.values(), key=lambda record: record.report_month)
        if result:
            logger.info("SEAJ 月度设备出货采集完成: 共 %d 个月度记录", len(result))
        else:
            logger.warning("SEAJ 未抓取到任何月度设备出货数据")
        return result

    def _get(self, url: str) -> Any | None:
        try:
            response = requests.get(
                url,
                headers=SEAJ_HEADERS,
                timeout=self.timeout,
                impersonate=self.impersonate,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("请求 SEAJ 页面失败 [%s]: %s", url, exc)
            return None
        if response.status_code != 200:
            logger.warning("请求 SEAJ 页面返回 HTTP %d [%s]", response.status_code, url)
            return None
        return response

    def _fetch_release_dates(self) -> dict[str, date]:
        response = self._get(SEAJ_RELEASE_DATES_URL)
        if response is None:
            return {}
        content_bytes = response_content_bytes(response)
        if not content_bytes:
            return {}
        save_raw_snapshot(
            SEAJ_SOURCE_NAME,
            SEAJ_RELEASE_DATES_FILENAME,
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
        )
        return parse_seaj_release_calendar_pdf(content_bytes)

    def _collect_historical(
        self,
        source_url: str | None,
        *,
        release_dates: dict[str, date],
        collected_at: str,
    ) -> list[SemiconductorEquipmentRecord]:
        if not source_url:
            logger.warning("SEAJ statistics 首页未找到历史设备出货 Excel 链接")
            return []

        response = self._get(source_url)
        if response is None:
            return []
        content_bytes = response_content_bytes(response)
        if not content_bytes:
            return []

        snapshot_path = save_raw_snapshot(
            SEAJ_SOURCE_NAME,
            SEAJ_HISTORICAL_XLS_FILENAME,
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
        )
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(snapshot_path, self.raw_root)
        rows = parse_seaj_historical_xls(
            content_bytes,
            start_year=START_YEAR,
            end_year=date.today().year,
        )
        return [
            self._record_from_item(
                row,
                source_url=source_url,
                content_hash=content_hash,
                snapshot_ref=snapshot_ref,
                release_dates=release_dates,
                collected_at=collected_at,
            )
            for row in rows
        ]

    def _collect_latest_pdf(
        self,
        source_url: str | None,
        listing_release_date: date | None,
        *,
        release_dates: dict[str, date],
        collected_at: str,
    ) -> list[SemiconductorEquipmentRecord]:
        if not source_url:
            return []
        response = self._get(source_url)
        if response is None:
            return []
        content_bytes = response_content_bytes(response)
        if not content_bytes:
            return []

        snapshot_path = save_raw_snapshot(
            SEAJ_SOURCE_NAME,
            SEAJ_LATEST_PDF_FILENAME,
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
        )
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(snapshot_path, self.raw_root)
        rows = self.pdf_parser.parse_pdf_bytes(
            content_bytes,
            release_date=listing_release_date,
            release_dates=release_dates,
        )
        return [
            self._record_from_item(
                row,
                source_url=source_url,
                content_hash=content_hash,
                snapshot_ref=snapshot_ref,
                release_dates=release_dates,
                collected_at=collected_at,
            )
            for row in rows
        ]

    def _record_from_item(
        self,
        item: dict[str, Any],
        *,
        source_url: str,
        content_hash: str,
        snapshot_ref: str,
        release_dates: dict[str, date],
        collected_at: str,
    ) -> SemiconductorEquipmentRecord:
        report_month = str(item["report_month"])
        year, month = parse_month_string(report_month)
        release_date = item.get("release_date")
        if not isinstance(release_date, date):
            release_date = release_dates.get(report_month) or _next_month_release_date(report_month)

        billings_raw = _first_text(item, "sales_3mma_raw", "billings_jpy_raw")
        yoy_raw = _first_text(item, "yoy_growth_3mma_raw", "yoy_reported")
        mom_raw = _first_text(item, "mom_growth_3mma_raw", "mom_reported")
        return SemiconductorEquipmentRecord(
            report_month=report_month,
            trade_date=get_month_end_date(year, month),
            billings_3mma_jpy=float(item["billings_3mma_jpy"]),
            yoy_growth_3mma=_optional_float(item.get("yoy_growth_3mma")),
            mom_growth_3mma=_optional_float(item.get("mom_growth_3mma")),
            unit="billion_jpy",
            source="SEAJ",
            source_url=source_url,
            release_date=release_date,
            data_status="actual",
            collected_at=collected_at,
            raw_content_sha256=content_hash,
            raw_snapshot_path=snapshot_ref,
            billings_jpy_raw=billings_raw,
            yoy_reported=yoy_raw,
            mom_reported=mom_raw,
            billings_raw=billings_raw,
            yoy_raw=yoy_raw,
            mom_raw=mom_raw,
        )


def _first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _next_month_release_date(report_month: str) -> date:
    year, month = parse_month_string(report_month)
    if month == 12:
        return date(year + 1, 1, 25)
    return date(year, month + 1, 25)
