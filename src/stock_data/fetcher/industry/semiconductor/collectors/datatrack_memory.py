"""TrendForce DataTrack 内存现货月度基准价格采集器 (DataTrackMemoryPriceCollector)。

遵循 tsmc.py 采集流程规范:
1. 在线拉取 TrendForce DataTrack JSON 数据端点 (6105: DRAM, 6106: NAND Wafer)；
2. 原始响应二进制 Gzip 存证归档至 RAW 目录，计算 SHA256 哈希与快照相对路径；
3. 解析为不可变 MemoryPriceBenchmarkRecord，完整保留源端字段 (value_raw, period_raw, indicator_id_raw)；
4. 输出按品类和月份排序的记录列表，供下游 2-Tier Curated 构建不可变事实表。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso, save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import MemoryPriceBenchmarkRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_datatrack_memory_price_json,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

DATATRACK_BASE_URL = (
    "https://datatrack-finwhale.trendforce.com:8000/api/v1/data/column?fields={field_id}"
)
DATATRACK_SOURCE_NAME = "datatrack"

DATATRACK_FIELDS: tuple[dict[str, Any], ...] = (
    {"field_id": 6105, "product_family": "DRAM", "name": "Mainstream DRAM Spot Price"},
    {"field_id": 6106, "product_family": "NAND", "name": "Mainstream NAND Flash Wafer Spot Price"},
)

DATATRACK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://datatrack.trendforce.com",
    "Referer": "https://datatrack.trendforce.com/",
}


class DataTrackMemoryPriceCollector:
    """TrendForce DataTrack 内存现货月度基准价格采集适配器。"""

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

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MemoryPriceBenchmarkRecord]:
        """在线采集 TrendForce DataTrack 内存月度现货价格历史与最新基准记录。"""
        del force  # DataTrack 当前无本地响应缓存；强制刷新由上层保留并传递到此。
        self.paths.datatrack_dir.mkdir(parents=True, exist_ok=True)
        records: list[MemoryPriceBenchmarkRecord] = []

        for field in DATATRACK_FIELDS:
            records.extend(
                self._collect_field(
                    field["field_id"],
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        if not records:
            logger.info("未抓取到任何 TrendForce DataTrack 内存基准价格数据")
            return []

        logger.info("TrendForce DataTrack 内存基准价格采集完成: 共 %d 条月度记录", len(records))
        return sorted(records, key=lambda r: (r.product_family, r.indicator_id, r.report_month))

    def _collect_field(
        self,
        field_id: int,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MemoryPriceBenchmarkRecord]:
        url = DATATRACK_BASE_URL.format(field_id=field_id)
        try:
            resp = requests.get(
                url,
                headers=DATATRACK_HEADERS,
                impersonate=self.impersonate,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning("抓取 DataTrack fields=%d 返回 HTTP %d", field_id, resp.status_code)
                return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("抓取 DataTrack fields=%d 异常: %s", field_id, exc)
            return []

        content_bytes = response_content_bytes(resp)
        if not content_bytes:
            logger.warning("DataTrack fields=%d 响应内容为空", field_id)
            return []

        # 原始 JSON Gzip 归档，供离线对账与可溯源校验
        snapshot_path = save_raw_snapshot(
            DATATRACK_SOURCE_NAME,
            f"datatrack_memory_fields_{field_id}.json.gz",
            content_bytes,
            base_dir=self.paths.semiconductor_dir,
            compress=True,
        )
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(snapshot_path, self.raw_root)
        collected_at = now_utc_iso()

        records = parse_datatrack_memory_price_json(
            content_bytes,
            source_url=url,
            collected_at=collected_at,
            raw_content_sha256=content_hash,
            raw_snapshot_path=snapshot_ref,
        )
        records = [
            record
            for record in records
            if (start_date is None or record.trade_date >= start_date)
            and (end_date is None or record.trade_date <= end_date)
        ]

        logger.info("成功抓取 DataTrack fields=%d: 共 %d 个月份基准点", field_id, len(records))
        return records
