"""CABIA 动力电池在线采集适配客户端（对接高可靠财联社电报流）。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.automotive.clients.cls import ClsBatteryClient

logger = logging.getLogger(__name__)

CABIA_ONLINE_BASE_URL = "https://batteryalliancechina.org"
CABIA_RESOURCE_API_URL = f"{CABIA_ONLINE_BASE_URL}/api/resources"
CABIA_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class CabiaOnlineClient:
    """动力电池装车量在线采集客户端，直接接入高可靠财联社（CLS）电报流。"""

    def __init__(
        self,
        raw_dir: Path | str,
        *,
        timeout: int = 15,
        impersonate: str = "chrome120",
        resource_api_url: str | None = None,
        cls_client: ClsBatteryClient | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.timeout = timeout
        self.impersonate = impersonate
        self.resource_api_url: str = resource_api_url or CABIA_RESOURCE_API_URL
        self.cls_client = cls_client or ClsBatteryClient(
            self.raw_dir,
            timeout=timeout,
            impersonate=impersonate,
        )
        self.last_errors: tuple[str, ...] = ()
        self.last_fetched_periods: tuple[str, ...] = ()

    def fetch(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 3,
    ) -> dict[str, dict[str, Any]]:
        """从财联社电报流增量捕获最新的 CABIA 动力电池装车量通报。"""
        self.last_errors = ()
        self.last_fetched_periods = ()
        results = self.cls_client.fetch(
            start_date=start_date,
            end_date=end_date,
            max_pages=max_pages,
        )
        self.last_errors = self.cls_client.last_errors
        self.last_fetched_periods = (
            tuple(sorted(results.keys())) if results else self.cls_client.last_fetched_periods
        )
        return results


__all__ = [
    "CABIA_HEADERS",
    "CABIA_ONLINE_BASE_URL",
    "CABIA_RESOURCE_API_URL",
    "CabiaOnlineClient",
    "requests",
]
