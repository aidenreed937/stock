"""SEMI 全球半导体设备市场统计 (WWSEMS) 季度公报在线采集器。

数据源:
- RAW 层: 调用方传入的 RAW 根目录下 semiconductor/semi/ 的源端 HTML 快照
- Curated 层: 由 endpoint registry + industry runner 按注册路径物化
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.semi_crawler import SemiEquipmentCrawler
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.transforms.semi import (
    build_semi_equipment_raw_frame,
)

logger = logging.getLogger(__name__)


class SemiEquipmentCollector:
    """SEMI 全球半导体设备销售公报 2-Tier ETL 采集器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.snapshot_dir = self.paths.semi_dir
        self.timeout = timeout
        self.impersonate = impersonate
        self.crawler = SemiEquipmentCrawler(
            raw_dir=self.paths.raw_root,
            timeout=timeout,
            impersonate=impersonate,
        )

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """执行在线采集并返回不含派生字段的 SEMI 设备出货 RAW 帧。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if start_date is not None or end_date is not None:
            new_items = self.crawler.fetch_range(
                start_date=start_date,
                end_date=end_date,
                force=force,
            )
        else:
            new_items = self.crawler.fetch_latest(force=force)
        if not new_items:
            return build_semi_equipment_raw_frame([])

        return build_semi_equipment_raw_frame(new_items)
