"""白酒批价采集器。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.consumer.models import LiquorWholesaleRecord
from stock_data.fetcher.industry.consumer.parsers import (
    JINRIJIA_URL,
    parse_liquor_price_text,
    save_liquor_raw_csv,
)

logger = logging.getLogger(__name__)


class LiquorPriceCrawler:
    """白酒行业渠道批发参考价轻量在线采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.consumer_dir = self.raw_dir / "consumer"

    def fetch_latest_liquor_price(self) -> dict[str, Any] | None:
        """在线抓取白酒最新批价快照。"""
        self.consumer_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info("正在抓取白酒批发参考价发布源: %s", JINRIJIA_URL)
            resp = requests.get(
                JINRIJIA_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                impersonate="chrome120",
                timeout=12,
            )
            if resp.status_code == 200:
                parsed = parse_liquor_price_text(resp.text)
                if parsed:
                    return parsed
        except Exception as e:
            logger.debug("抓取白酒批价异常: %s", e)

        return None


class LiquorWholesaleCollector:
    """高端白酒周度渠道一批价与动销采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.consumer_raw_dir = self.raw_dir / "consumer"
        self.crawler = LiquorPriceCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[LiquorWholesaleRecord]:
        """执行白酒一批价采集: 在线抓取最新周度批价并落盘。"""
        self.consumer_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.consumer_raw_dir / "liquor_wholesale_weekly.csv"

        live_data = self.crawler.fetch_latest_liquor_price()
        if not live_data or not live_data.get("report_date"):
            logger.warning("在线抓取白酒批价失败")
            return []

        d_key = str(live_data["report_date"])
        rec_live = LiquorWholesaleRecord(
            report_date=d_key,
            trade_date=live_data["trade_date"],
            moutai_loose_price_cny=live_data.get("moutai_loose_price_cny"),
            moutai_boxed_price_cny=live_data.get("moutai_boxed_price_cny"),
            wuliangye_puwu_price_cny=live_data.get("wuliangye_puwu_price_cny"),
            guojiao1573_price_cny=live_data.get("guojiao1573_price_cny"),
            moutai_loose_price_yoy=None,
            moutai_loose_price_mom=None,
            unit="cny_per_bottle",
            source=live_data.get("source") or "TodayLiquorPrice",
            source_url=live_data.get("source_url") or JINRIJIA_URL,
            release_date=live_data.get("release_date"),
            data_status="actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[LiquorWholesaleRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_liquor_raw_csv(file_path, records)


__all__ = ["LiquorPriceCrawler", "LiquorWholesaleCollector"]
