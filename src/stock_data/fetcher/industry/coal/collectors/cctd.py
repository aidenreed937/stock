"""CCTD 动力煤价格采集器。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import requests

from stock_data.fetcher.industry.base_parser import HtmlParserProtocol
from stock_data.fetcher.industry.coal.models import CoalMarketRecord
from stock_data.fetcher.industry.coal.parsers import (
    CctdCoalPriceHtmlParser,
    save_coal_raw_csv,
)
from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

CCTD_URL = "https://www.cctd.com.cn/index.php?a=lists&c=index&catid=520&m=content"
CCTD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class CoalMarketCrawler:
    """CCTD 秦皇岛动力煤价格页克制爬虫。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        parser: HtmlParserProtocol[dict[str, Any]] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "coal" / "cctd"
        self.parser = parser or CctdCoalPriceHtmlParser()

    def fetch_latest_q5500(self, force: bool = False) -> dict[str, Any] | None:
        """抓取 CCTD 最新一期 Q5500 平仓价并归档页面快照。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self.snapshot_dir / "cctd_q5500_latest.html"

        if not force and snapshot_file.exists() and snapshot_file.stat().st_size > 0:
            try:
                html_text = snapshot_file.read_text(encoding="utf-8")
                parsed = self.parser.parse(html_text)
                if parsed:
                    parsed["source"] = "CCTD"
                    parsed["source_url"] = CCTD_URL
                    parsed["release_date"] = parsed["report_date"]
                    parsed["data_status"] = "actual"
                    parsed["collected_at"] = now_utc_iso()
                    logger.info(
                        "命中 CCTD 本地 RAW 快照: %s 元/吨 (%s)",
                        parsed["q5500_fob_price_cny"],
                        parsed["report_date"],
                    )
                    return parsed
            except Exception as e:
                logger.debug("读取 CCTD 本地快照失败，将在线重抓: %s", e)

        try:
            logger.info("正在抓取 CCTD 秦皇岛动力煤价格页: %s", CCTD_URL)
            resp = requests.get(CCTD_URL, headers=CCTD_HEADERS, timeout=20)
            if resp.status_code != 200:
                logger.warning("CCTD 页面返回 HTTP %d", resp.status_code)
                return None
            resp.encoding = "gbk"
            html_text = resp.text
        except Exception as e:
            logger.warning("访问 CCTD 页面异常: %s", e)
            return None

        try:
            snapshot_file.write_text(html_text, encoding="utf-8")
        except Exception as e:
            logger.debug("保存 CCTD 快照失败: %s", e)

        parsed = self.parser.parse(html_text)
        if parsed is None:
            logger.warning("CCTD 页面解析失败 (格式可能已改版)")
            return None

        parsed["source"] = "CCTD"
        parsed["source_url"] = CCTD_URL
        parsed["release_date"] = parsed["report_date"]
        parsed["data_status"] = "actual"
        parsed["collected_at"] = now_utc_iso()
        logger.info(
            "成功抓取 CCTD Q5500 平仓价: %s 元/吨 (%s)",
            parsed["q5500_fob_price_cny"],
            parsed["report_date"],
        )
        return parsed


class CoalMarketCollector:
    """煤炭行业动力煤平仓价与电厂库存日耗采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.coal_raw_dir = self.raw_dir / "coal"
        self.crawler = CoalMarketCrawler(raw_dir=self.raw_dir)

    def collect(self, force: bool = False) -> list[CoalMarketRecord]:
        """执行煤炭数据采集: 抓取 CCTD 最新 Q5500 平仓价并落盘。"""
        self.coal_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.coal_raw_dir / "coal_market_weekly.csv"

        live_data = self.crawler.fetch_latest_q5500(force=force)
        if not live_data or not live_data.get("report_date"):
            logger.warning("在线抓取 CCTD Q5500 平仓价失败")
            return []

        d_key = str(live_data["report_date"])
        try:
            t_date = date.fromisoformat(d_key)
        except ValueError:
            logger.warning("CCTD report_date 非 ISO 日期，跳过本次记录: %s", d_key)
            return []
        rec_live = CoalMarketRecord(
            report_date=d_key,
            trade_date=t_date,
            q5500_fob_price_cny=live_data.get("q5500_fob_price_cny"),
            coking_coal_price_cny=None,
            power_plant_inventory_million_ton=None,
            power_plant_daily_burn_ten_thousand_ton=None,
            power_plant_available_days=None,
            qinhuangdao_inventory_million_ton=None,
            q5500_price_yoy=None,
            q5500_price_mom=None,
            unit="cny_per_ton/million_tons/days",
            source=live_data.get("source") or "CCTD",
            source_url=live_data.get("source_url") or "https://www.cctd.com.cn/",
            release_date=date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else None,
            data_status=live_data.get("data_status") or "actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[CoalMarketRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_coal_raw_csv(file_path, records)


__all__ = ["CCTD_HEADERS", "CCTD_URL", "CoalMarketCollector", "CoalMarketCrawler"]
