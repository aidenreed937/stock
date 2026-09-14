"""台积电官方先进封装与财务拆解采集适配器 (TsmcAdvancedPackagingRevenueCollector).

基于 2-Tier ETL 规范，从结构化 RAW 事实表与法定 Management Report 快照中加载
官方真实季度财务拆解数据，全量保持 actual 状态，零未来函数。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.semiconductor.collectors.tsmc_adv_pkg_crawler import (
    TsmcAdvPkgRevenueCrawler,
)
from stock_data.fetcher.industry.semiconductor.models import TsmcAdvancedPackagingRevenueRecord
from stock_data.fetcher.industry.semiconductor.parsers.adv_pkg_revenue import (
    load_tsmc_adv_pkg_revenue_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)


class TsmcAdvancedPackagingRevenueCollector:
    """台积电官方先进封装财务拆解采集器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root

    def collect(
        self, force: bool = False, **_kwargs: Any
    ) -> list[TsmcAdvancedPackagingRevenueRecord]:
        """采集并校验台积电官方先进封装财务拆解记录。

        1. 检查本地 RAW CSV 并提取当前最大已记录季度；
        2. 触发在线增量爬虫嗅探更新的季度管理报告；
        3. 验证 SHA-256 并加载全部历史记录。
        """
        csv_file = self.paths.tsmc_adv_pkg_revenue_csv
        current_max_quarter: str | None = None
        fallback_pkg_pct: float | None = 0.1000

        if csv_file.exists():
            try:
                # 尝试预加载获取已有最大季度
                existing_records = load_tsmc_adv_pkg_revenue_raw_csv(
                    csv_file,
                    project_root=self.raw_root.parent,
                    verify_hash=False,
                )
                if existing_records:
                    current_max_quarter = existing_records[-1].report_quarter
                    if existing_records[-1].packaging_testing_others_pct is not None:
                        fallback_pkg_pct = existing_records[-1].packaging_testing_others_pct
            except Exception as exc:  # noqa: BLE001
                logger.debug("读取已有 TSMC 记录用于获取当前最大季度失败: %s", exc)

        # 在线增量探测与存证下载
        try:
            crawler = TsmcAdvPkgRevenueCrawler(raw_dir=self.raw_root)
            crawler.sync_incremental(
                current_max_quarter=current_max_quarter,
                fallback_pkg_pct=fallback_pkg_pct,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TSMC 官方财务拆解在线增量更新异常 (将回退至本地数据): %s", exc)

        if not csv_file.exists():
            logger.warning("未找到台积电官方财务 RAW CSV: %s", csv_file)
            return []

        records = load_tsmc_adv_pkg_revenue_raw_csv(
            csv_file,
            project_root=self.raw_root.parent,
            verify_hash=True,
        )
        logger.info("台积电官方先进封装财务拆解加载完成: 共 %d 条季度记录", len(records))
        return records
