"""国家能源局 (NEA) 官方政务通报轻量与克制爬虫 (NeaBulletinCrawler)。"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

NEA_BASE_URL = "http://www.nea.gov.cn"
NEA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def parse_solar_capacity_from_text(text: str) -> tuple[float | None, float | None]:
    """从国家能源局通报正文中正则提取太阳能累计装机 (GW) 与同比增速。

    通报示例: "其中，太阳能发电装机容量12.9亿千瓦，同比增长16.1%"
    """
    clean_text = text.replace(" ", "").replace("\n", "").replace("\r", "")

    # 1. 正则匹配累计装机容量
    cap_gw: float | None = None
    pattern_cap = re.search(
        r"太阳能发电装机容量(?:约)?(\d+\.?\d*)\s*(亿千瓦|万千瓦|吉瓦|GW)", clean_text
    )
    if pattern_cap:
        val = float(pattern_cap.group(1))
        unit = pattern_cap.group(2)
        if unit == "亿千瓦":
            cap_gw = round(val * 100.0, 2)  # 1亿千瓦 = 100 GW
        elif unit == "万千瓦":
            cap_gw = round(val * 0.01, 2)
        elif unit in ("吉瓦", "GW"):
            cap_gw = round(val, 2)

    # 2. 正则匹配同比增速
    yoy_val: float | None = None
    pattern_yoy = re.search(
        r"太阳能发电装机容量[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        clean_text,
    )
    if pattern_yoy:
        yoy_val = round(float(pattern_yoy.group(1)) / 100.0, 4)

    return cap_gw, yoy_val


class NeaBulletinCrawler:
    """国家能源局《全国电力工业统计数据》克制爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.nea_dir = self.raw_dir / "nea"
        self.cache_file = self.nea_dir / "nea_bulletins.json.gz"

    def fetch_latest_bulletins(self) -> dict[str, dict[str, Any]]:
        """从国家能源局官网克制抓取最新电力统计通报并合并本地缓存。"""
        self.nea_dir.mkdir(parents=True, exist_ok=True)
        cached_data: dict[str, dict[str, Any]] = self._load_cache()

        # 扫描官网首页获取通报链接 (仅发单次轻量 GET 请求)
        try:
            logger.info("正在克制扫描国家能源局官网首页发布列表: %s", NEA_BASE_URL)
            r = requests.get(NEA_BASE_URL, headers=NEA_HEADERS, timeout=10)
            if r.status_code != 200:
                logger.warning("访问国家能源局官网首页返回 HTTP %d", r.status_code)
                return cached_data
            r.encoding = "utf-8"
        except Exception as e:
            logger.warning("访问国家能源局首页异常: %s", e)
            return cached_data

        soup = BeautifulSoup(r.text, "html.parser")
        news_candidates: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href_str = str(a["href"])
            if "全国电力统计数据" in title or "全国电力工业统计数据" in title:
                full_url = (
                    href_str
                    if href_str.startswith("http")
                    else f"{NEA_BASE_URL}/{href_str.lstrip('/')}"
                )
                news_candidates.append((title, full_url))

        # 过滤未抓取的新通报
        now_iso = now_utc_iso()
        for title, url in news_candidates:
            # 正则解析通报对应月份 (如 2026年1-7月份 -> 2026-07)
            m_match = re.search(r"(\d{4})年(?:1-)?(\d{1,2})月份", title)
            if not m_match:
                continue
            yr, mo = int(m_match.group(1)), int(m_match.group(2))
            month_key = f"{yr}-{mo:02d}"

            if month_key in cached_data and cached_data[month_key].get("cumulative_gw") is not None:
                continue

            logger.info("发现国家能源局新统计通报: [%s] -> %s", title, url)
            time.sleep(1.0)  # 克制爬取间隔
            try:
                doc_r = requests.get(url, headers=NEA_HEADERS, timeout=10)
                if doc_r.status_code == 200:
                    doc_r.encoding = "utf-8"
                    doc_soup = BeautifulSoup(doc_r.text, "html.parser")
                    body_text = doc_soup.get_text()
                    cap_gw, yoy = parse_solar_capacity_from_text(body_text)
                    if cap_gw is not None:
                        logger.info(
                            "✅ 成功从国家能源局官方通报解析出 %s 太阳能累计装机: %.2f GW (YoY: %s)",
                            month_key,
                            cap_gw,
                            f"{yoy * 100:.1f}%" if yoy else "N/A",
                        )
                        cached_data[month_key] = {
                            "report_month": month_key,
                            "title": title,
                            "url": url,
                            "cumulative_gw": cap_gw,
                            "yoy_growth": yoy,
                            "release_date": date.today().isoformat(),
                            "collected_at": now_iso,
                        }
            except Exception as e:
                logger.error("抓取通报文章详情失败 [%s]: %s", url, e)

        self._save_cache(cached_data)
        return cached_data

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """读取本地已压缩归档的官方通报缓存。"""
        if not self.cache_file.exists():
            return {}
        try:
            from typing import cast

            with gzip.open(self.cache_file, "rt", encoding="utf-8") as f:
                return cast("dict[str, dict[str, Any]]", json.load(f))
        except Exception as e:
            logger.warning("读取 NEA 通报缓存失败: %s", e)
            return {}

    def _save_cache(self, data: dict[str, dict[str, Any]]) -> None:
        """持久化官方通报缓存。"""
        try:
            with gzip.open(self.cache_file, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存 NEA 通报缓存失败: %s", e)
