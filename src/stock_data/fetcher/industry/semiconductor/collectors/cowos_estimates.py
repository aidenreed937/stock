"""智库 CoWoS 产能测算与供需推演采集适配器 (CowosCapacityEstimatesCollector).

从公开智库研报/公报快照中加载 CoWoS 月产能测算数据，
严格标记 forecast/estimate 状态并绑定 published_date，与官方 actual 表物理隔离。
"""

from __future__ import annotations

import logging
from pathlib import Path

from stock_data.fetcher.industry.semiconductor.models import CowosCapacityEstimateRecord
from stock_data.fetcher.industry.semiconductor.parsers.cowos_estimates import (
    load_cowos_capacity_estimates_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)


class CowosCapacityEstimatesCollector:
    """智库 CoWoS 产能前瞻测算采集器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root

    def collect(self) -> list[CowosCapacityEstimateRecord]:
        """采集并校验智库 CoWoS 产能前瞻测算记录。"""
        csv_file = self.paths.cowos_estimates_csv
        if not csv_file.exists():
            logger.warning("未找到 CoWoS 智库测算 RAW CSV: %s", csv_file)
            return []

        records = load_cowos_capacity_estimates_raw_csv(
            csv_file,
            project_root=self.raw_root.parent,
            verify_hash=True,
        )
        logger.info("CoWoS 智库测算记录加载完成: 共 %d 条记录", len(records))
        return records
