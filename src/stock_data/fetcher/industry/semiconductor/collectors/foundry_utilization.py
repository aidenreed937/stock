"""全球晶圆代工 (TSMC / SMIC) 官方产能利用率与存量平衡表 2-Tier ETL 清洗器。

严格遵循 2-Tier 原则与架构边界:
1. RAW 层保存官方公告源文本/源文件，collector 不再读取加工后的 CSV 作为第二事实源。
2. Curated 层由 endpoint registry + industry runner 按注册路径物化，transform 仅在两家
   公司值同时存在时生成带方法标记的代表性代理值，并划分 (utilization_regime)。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler import (
    FoundryUtilizationCrawler,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths
from stock_data.fetcher.industry.semiconductor.schemas import FOUNDRY_RAW_SCHEMA
from stock_data.fetcher.industry.semiconductor.transforms import build_foundry_raw_frame

logger = logging.getLogger(__name__)

RAW_SCHEMA = FOUNDRY_RAW_SCHEMA


class FoundryUtilizationCollector:
    """全球晶圆代工产能利用率 2-Tier ETL 处理器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.snapshot_dir = self.paths.foundry_dir
        self.timeout = timeout
        self.impersonate = impersonate
        self.crawler = FoundryUtilizationCrawler(
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
        """执行在线采集并返回不含加权利用率与相态的 RAW 帧。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if start_date is not None or end_date is not None:
            new_items = self.crawler.fetch_range(
                start_date=start_date,
                end_date=end_date,
                force=force,
            )
        else:
            new_items = self.crawler.fetch_latest(force=force)
        return build_foundry_raw_frame(new_items)
