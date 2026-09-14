"""TrendForce DRAM/NAND 价格在线采集器。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso, save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_trendforce_memory_price_html,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.transforms import build_memory_price_raw_frame

logger = logging.getLogger(__name__)

TRENDFORCE_PRICE_PAGES = (
    {
        "product_family": "DRAM",
        "price_scope": "contract",
        "page_slug": "dram_contract",
        "url": "https://www.trendforce.com/price/dram/dram_contract",
    },
    {
        "product_family": "NAND",
        "price_scope": "contract",
        "page_slug": "flash_contract",
        "url": "https://www.trendforce.com/price/flash/flash_contract",
    },
    {
        "product_family": "NAND",
        "price_scope": "spot",
        "page_slug": "flash_spot",
        "url": "https://www.trendforce.com/price/flash/flash_spot",
    },
    {
        "product_family": "NAND",
        "price_scope": "wafer_contract",
        "page_slug": "wafer_contract",
        "url": "https://www.trendforce.com/price/flash/wafer_contract",
    },
)

TRENDFORCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class MemoryPriceCollector:
    """TrendForce 当前公开 DRAM/NAND 价格采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 20,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.timeout = timeout
        self.impersonate = impersonate

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """在线抓取 TrendForce 价格页，并返回源端字段优先的 RAW DataFrame。"""
        del force
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"TrendForce 内存价格日期范围无效: {start_date} > {end_date}")
        self.paths.semiconductor_dir.mkdir(parents=True, exist_ok=True)
        collected_at = now_utc_iso()
        rows: list[dict[str, Any]] = []
        for page in TRENDFORCE_PRICE_PAGES:
            rows.extend(
                self._collect_page(
                    page,
                    collected_at=collected_at,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return build_memory_price_raw_frame(rows)

    def _collect_page(
        self,
        page: dict[str, str],
        *,
        collected_at: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        source_url = page["url"]
        response = self._get(source_url)
        if response is None:
            return []
        content_bytes = response_content_bytes(response)
        if not content_bytes:
            logger.warning("TrendForce 价格页响应为空 [%s]", page["page_slug"])
            return []

        snapshot_path = save_raw_snapshot(
            "trendforce",
            f"{page['page_slug']}.html.gz",
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
            compress=True,
        )
        html_text = getattr(response, "text", "") or content_bytes.decode("utf-8", errors="ignore")
        rows = parse_trendforce_memory_price_html(
            html_text,
            product_family=page["product_family"],
            price_scope=page["price_scope"],
            page_slug=page["page_slug"],
            source_url=source_url,
            collected_at=collected_at,
            raw_content_hash=raw_content_sha256(content_bytes),
            raw_snapshot_path=raw_snapshot_path_value(snapshot_path, self.raw_root),
        )
        return [
            row
            for row in rows
            if (start_date is None or row["trade_date"] >= start_date)
            and (end_date is None or row["trade_date"] <= end_date)
        ]

    def _get(self, url: str) -> Any | None:
        try:
            response = requests.get(
                url,
                headers=TRENDFORCE_HEADERS,
                timeout=self.timeout,
                impersonate=self.impersonate,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TrendForce 价格页请求异常 [%s]: %s", url, exc)
            return None
        if response.status_code != 200:
            logger.warning("TrendForce 价格页请求失败 [%s]: HTTP %s", url, response.status_code)
            return None
        return response
