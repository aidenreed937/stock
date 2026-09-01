"""中国创新药海外 License-out (BD) 交易采集适配器 (PharmaBdCollector)。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from stock_data.fetcher.industry.pharma.crawler import PharmaAnnouncementCrawler
from stock_data.fetcher.industry.pharma.ledger import (
    aggregate_events_to_monthly,
    load_pharma_raw_csv,
    parse_deals_ledger_data,
    save_pharma_raw_csv,
)
from stock_data.fetcher.industry.pharma.models import PharmaLicenseOutRecord
from stock_data.fetcher.industry.pharma.transform import (
    assets_to_frame,
    deals_to_frame,
    events_to_frame,
)

logger = logging.getLogger(__name__)


class PharmaBdCollector:
    """中国创新药海外 License-out (BD) 交易采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        processed_dir: Path | str = "data/processed/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.pharma_dir = self.raw_dir / "pharma"
        self.processed_dir = Path(processed_dir)
        self.crawler = PharmaAnnouncementCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[PharmaLicenseOutRecord]:
        """执行创新药出海 BD 数据采集: 在线检索最新公告并合并落盘，以最新采集为准。"""
        self.pharma_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = self.pharma_dir / "deals_ledger.yaml"

        existing_deals: list[dict[str, Any]] = []
        if ledger_path.exists():
            with ledger_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                existing_deals = data.get("deals", [])

        # 在线爬取 A/H 股交易所最新对外许可公告
        live_deals = self.crawler.fetch_latest_deals()
        if live_deals:
            deal_map = {d["deal_id"]: d for d in existing_deals}
            for d in live_deals:
                deal_map[d["deal_id"]] = d
            all_deals = sorted(
                list(deal_map.values()), key=lambda x: str(x.get("announcement_date", ""))
            )
            with ledger_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump({"deals": all_deals}, f, allow_unicode=True, sort_keys=False)
            logger.info("在线采集与合并创新药出海 BD 公告共 %d 笔", len(all_deals))
        else:
            all_deals = existing_deals

        return self.process_ledger_deals(all_deals)

    def process_ledger_deals(self, raw_deals: list[dict[str, Any]]) -> list[PharmaLicenseOutRecord]:
        """解析结构化交易底账，落盘 Processed 实体层与 RAW 快照。"""
        deals, assets, events = parse_deals_ledger_data(raw_deals)

        # 落盘 Processed 实体层
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        deals_to_frame(deals).write_parquet(self.processed_dir / "pharma_bd_deals.parquet")
        assets_to_frame(assets).write_parquet(self.processed_dir / "pharma_bd_assets.parquet")
        events_to_frame(events).write_parquet(self.processed_dir / "pharma_bd_events.parquet")
        logger.info(
            "已落盘 Processed 实体层: %d 笔 Deals, %d 条 Assets, %d 个 Events",
            len(deals),
            len(assets),
            len(events),
        )

        records = aggregate_events_to_monthly(deals, assets, events)
        self.save_to_raw_csv(self.pharma_dir / "license_out_monthly.csv", records)
        return records

    def load_from_ledger_yaml(self, file_path: Path | str) -> list[PharmaLicenseOutRecord]:
        """从外部指定 YAML 底账文件解析并处理。"""
        p = Path(file_path)
        if not p.exists():
            return []
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return self.process_ledger_deals(data.get("deals", []))

    def save_to_raw_csv(self, file_path: Path | str, records: list[PharmaLicenseOutRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pharma_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[PharmaLicenseOutRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_pharma_raw_csv(file_path)
