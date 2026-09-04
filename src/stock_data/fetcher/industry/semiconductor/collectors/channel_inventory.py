"""Avnet/Arrow 渠道库存 SEC companyfacts 在线采集器。"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import requests

from stock_data.fetcher.industry.common import now_utc_iso, save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_channel_inventory_companyfacts,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_channel_inventory_raw_frame,
)

logger = logging.getLogger(__name__)

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_COMPANYFACTS_SOURCE_NAME = "sec_companyfacts"
SEC_COMPANYFACTS_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "stock-data-semiconductor/1.0 contact@example.com"),
    "Accept": "application/json",
}

CHANNEL_DISTRIBUTORS = (
    {"company": "Arrow Electronics", "symbol": "ARW", "cik": "0000007536"},
    {"company": "Avnet", "symbol": "AVT", "cik": "0000008858"},
)


class ChannelInventoryCollector:
    """渠道商季度库存与营业成本采集适配器。"""

    def __init__(self, raw_dir: Path | str, timeout: int = 20) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.timeout = timeout

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """在线抓取 SEC companyfacts，并返回源端字段优先的 RAW DataFrame。"""
        del force
        self.paths.semiconductor_dir.mkdir(parents=True, exist_ok=True)
        collected_at = now_utc_iso()
        rows: list[dict[str, Any]] = []
        for company in CHANNEL_DISTRIBUTORS:
            rows.extend(self._collect_company(company, collected_at=collected_at))

        rows = [
            row
            for row in rows
            if _date_in_range(row.get("trade_date"), start_date=start_date, end_date=end_date)
        ]
        return build_channel_inventory_raw_frame(rows)

    def _collect_company(
        self,
        company: dict[str, str],
        *,
        collected_at: str,
    ) -> list[dict[str, Any]]:
        cik = company["cik"]
        url = SEC_COMPANYFACTS_URL.format(cik=cik)
        response = self._get(url)
        if response is None:
            return []
        content_bytes = response_content_bytes(response)
        if not content_bytes:
            logger.warning("SEC companyfacts 响应为空 [%s]", company["symbol"])
            return []

        snapshot_path = save_raw_snapshot(
            SEC_COMPANYFACTS_SOURCE_NAME,
            f"{company['symbol'].lower()}_companyfacts.json.gz",
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
            compress=True,
        )
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = json.loads(content_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            logger.warning("SEC companyfacts 响应不是 JSON 对象 [%s]", company["symbol"])
            return []

        return parse_channel_inventory_companyfacts(
            payload,
            company=company["company"],
            symbol=company["symbol"],
            source_url=url,
            collected_at=collected_at,
            raw_content_hash=raw_content_sha256(content_bytes),
            raw_snapshot_path=raw_snapshot_path_value(snapshot_path, self.raw_root),
        )

    def _get(self, url: str) -> Any | None:
        try:
            response = requests.get(url, headers=SEC_COMPANYFACTS_HEADERS, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC companyfacts 请求异常 [%s]: %s", url, exc)
            return None
        if response.status_code != 200:
            logger.warning("SEC companyfacts 请求失败 [%s]: HTTP %s", url, response.status_code)
            return None
        return response


def _date_in_range(
    value: object,
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    if not isinstance(value, date):
        return False
    if start_date is not None and value < start_date:
        return False
    if end_date is not None and value > end_date:
        return False
    return True
