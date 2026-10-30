"""农业农村部生猪产品数据采集器。"""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from stock_data.fetcher.industry.agriculture.models import AgriculturePorkRecord
from stock_data.fetcher.industry.agriculture.parsers import (
    MaraPorkHtmlParser,
    save_pork_raw_csv,
)
from stock_data.fetcher.industry.base_parser import HtmlParserProtocol
from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string

logger = logging.getLogger(__name__)

MARA_JDSJ_ROOT = "https://www.moa.gov.cn/ztzl/szcpxx/jdsj"
MARA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
FETCH_INTERVAL_SECONDS = 3.0


class MaraPorkCrawler:
    """农业农村部生猪产品数据月度表格页克制爬虫。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        parser: HtmlParserProtocol[dict[str, Any]] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.mara_dir = self.raw_dir / "agriculture" / "mara"
        self.parser = parser or MaraPorkHtmlParser()

    def _get(self, url: str, timeout: int = 20) -> requests.Response | None:
        try:
            resp = requests.get(url, headers=MARA_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp
            logger.warning("农业农村部页面返回 HTTP %d: %s", resp.status_code, url)
        except Exception as e:
            logger.warning("访问农业农村部页面异常 [%s]: %s", url, e)
        return None

    def discover_latest_month(self, max_tries: int = 6) -> str | None:
        """从当前月往前逐月探测 jdsj 月度页，首个 200 即最新已发布月份。"""
        today = date.today()
        for offset in range(max_tries):
            year = today.year
            month = today.month - offset
            while month <= 0:
                year -= 1
                month += 12
            month_key = f"{year:04d}-{month:02d}"
            url = f"{MARA_JDSJ_ROOT}/{year}/{month_key.replace('-', '')}/"
            resp = self._get(url, timeout=15)
            if resp is not None:
                logger.info("探测到最新生猪月度数据页: %s", month_key)
                return month_key
            time.sleep(FETCH_INTERVAL_SECONDS)
        return None

    def fetch_latest_month(self, force: bool = False) -> dict[str, Any] | None:
        """抓取最新一期生猪月度数据页并解析，同时归档页面 HTML 快照。"""
        self.mara_dir.mkdir(parents=True, exist_ok=True)

        if not force:
            existing_snapshots = sorted(self.mara_dir.glob("jdsj_*.html"))
            if existing_snapshots:
                latest_snap = existing_snapshots[-1]
                if latest_snap.stat().st_size > 0:
                    try:
                        html_text = latest_snap.read_text(encoding="utf-8")
                        parsed = self.parser.parse(html_text)
                        if parsed:
                            parsed["source"] = "MARA"
                            parsed["source_url"] = f"{MARA_JDSJ_ROOT}/"
                            parsed["release_date"] = None
                            parsed["data_status"] = "actual"
                            parsed["collected_at"] = now_utc_iso()
                            logger.info(
                                "命中农业农村部本地 RAW 快照 [%s]: 能繁=%s 万头, 价格=%s 元/公斤",
                                latest_snap.name,
                                parsed.get("sow_stock_million_heads"),
                                parsed.get("pig_price_cny_per_kg"),
                            )
                            return parsed
                    except Exception as e:
                        logger.debug("读取本地快照失败，将在线重抓: %s", e)

        month_key = self.discover_latest_month()
        if month_key is None:
            logger.warning("未探测到农业农村部生猪月度数据页")
            return None

        year, month = month_key.split("-")
        url = f"{MARA_JDSJ_ROOT}/{year}/{year}{month}/"
        resp = self._get(url)
        if resp is None:
            return None

        snapshot_file = self.mara_dir / f"jdsj_{year}{month}.html"
        try:
            snapshot_file.write_text(resp.text, encoding="utf-8")
        except Exception as e:
            logger.debug("保存农业农村部月度快照失败: %s", e)

        parsed = self.parser.parse(resp.text)
        if parsed is None:
            logger.warning("农业农村部 %s 月度页解析失败", month_key)
            return None

        parsed["source"] = "MARA"
        parsed["source_url"] = url
        parsed["release_date"] = None
        parsed["data_status"] = "actual"
        parsed["collected_at"] = now_utc_iso()
        logger.info(
            "成功抓取农业农村部 %s 生猪数据: 能繁=%s 万头, 价格=%s 元/公斤",
            month_key,
            parsed.get("sow_stock_million_heads"),
            parsed.get("pig_price_cny_per_kg"),
        )
        return parsed


class AgriculturePorkCollector:
    """生猪养殖与产能周期采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.agri_raw_dir = self.raw_dir / "agriculture"
        self.crawler = MaraPorkCrawler(raw_dir=self.raw_dir)

    def collect(self, force: bool = False) -> list[AgriculturePorkRecord]:
        """执行生猪产能数据采集: 抓取农业农村部最新月度通报并落盘。"""
        self.agri_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.agri_raw_dir / "pork_capacity_monthly.csv"

        live_data = self.crawler.fetch_latest_month(force=force)
        if not live_data or not live_data.get("report_month"):
            logger.warning("在线抓取农业农村部生猪月度通报失败")
            return []

        m_key = str(live_data["report_month"])
        yr, mo = parse_month_string(m_key)
        t_date = get_month_end_date(yr, mo)
        rec_live = AgriculturePorkRecord(
            report_month=m_key,
            trade_date=t_date,
            sow_stock_million_heads=live_data.get("sow_stock_million_heads"),
            sow_stock_yoy=None,
            sow_stock_mom=None,
            pig_price_cny_per_kg=live_data.get("pig_price_cny_per_kg"),
            pig_price_yoy=None,
            hog_to_grain_ratio=live_data.get("hog_to_grain_ratio"),
            pig_farming_profit_cny_head=live_data.get("pig_farming_profit_cny_head"),
            unit="million_heads/cny_per_kg",
            source=live_data.get("source") or "MARA/NBS",
            source_url=live_data.get("source_url") or "http://www.moa.gov.cn/",
            release_date=date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else None,
            data_status=live_data.get("data_status") or "actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[AgriculturePorkRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pork_raw_csv(file_path, records)


__all__ = [
    "FETCH_INTERVAL_SECONDS",
    "MARA_HEADERS",
    "MARA_JDSJ_ROOT",
    "AgriculturePorkCollector",
    "MaraPorkCrawler",
]
