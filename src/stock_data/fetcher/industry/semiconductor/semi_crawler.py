"""SEMI 全球半导体设备市场统计 (WWSEMS) 季度公报在线爬虫与解析器。

数据源: SEMI (https://www.semi.org/en/news-media/press-releases) 与 PR Newswire
季度初 (3月、6月、9月、12月) 官方发布上季度全球及中国大陆半导体设备出货公报。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag
from curl_cffi import requests

logger = logging.getLogger(__name__)

SEMI_PR_URL = "https://www.semi.org/en/news-media/press-releases"
SEMI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# 季度文本映射
QUARTER_WORDS_MAP = {
    "first quarter": 1,
    "second quarter": 2,
    "third quarter": 3,
    "fourth quarter": 4,
    "q1": 1,
    "q2": 2,
    "q3": 3,
    "q4": 4,
}


class SemiEquipmentCrawler:
    """SEMI 官方 WWSEMS 季度设备出货公报在线采集爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "semiconductor" / "semi"

    def parse_article_text(
        self, text: str, source_url: str = "", default_date: date | None = None
    ) -> dict[str, Any] | None:
        """从新闻通报文本中结构化提取全球及中国大陆设备出货额与报告季度。"""
        if not text:
            return None

        # 1. 提取年份与季度: 例如 "first quarter of 2026", "Q3 2024", "third quarter of 2024"
        q_match = re.search(
            r"(first quarter|second quarter|third quarter|fourth quarter|q[1-4])\s+(?:of\s+)?(\d{4})",
            text,
            re.IGNORECASE,
        )
        if not q_match:
            return None

        q_name, year_str = q_match.groups()
        q_num = QUARTER_WORDS_MAP.get(q_name.lower())
        if not q_num:
            return None
        year = int(year_str)
        report_quarter = f"{year}-Q{q_num}"

        # 2. 提取全球出货总额 (US$XX.XX billion)
        # 例如: "global semiconductor equipment billings increased 14% year-over-year to US$36.55 billion"
        # 例如: "increased 19% year-over-year to US$30.38 billion in the third quarter"
        # 例如: "billings of $26.8 billion in the second quarter"
        billings_match = re.search(
            r"(?:increased|reached|registered|sales of|billings of|to)\s+(?:US)?\$([\d\.]+)\s*billion",
            text,
            re.IGNORECASE,
        )
        if not billings_match:
            # 备选匹配: "$30.38 billion"
            billings_match = re.search(
                r"\$([\d\.]+)\s*billion\s+(?:in\s+the\s+)?(?:first|second|third|fourth|q[1-4])",
                text,
                re.IGNORECASE,
            )
            if not billings_match:
                return None

        global_billings = float(billings_match.group(1))

        # 3. 提取中国大陆采购额 (China $XX.XX billion)
        # 例如: "China ... $12.8 billion", "investments from China ... $49.6 billion"
        china_match = re.search(
            r"China[^\.\n]*?(?:spending|investments|sales|billings)?[^\.\n]*?\$([\d\.]+)\s*billion",
            text,
            re.IGNORECASE,
        )
        china_billings = float(china_match.group(1)) if china_match else None

        # 4. 提取发布日期: 例如 "June 4, 2026", "December 2, 2024", "April 9, 2025"
        rel_date = default_date
        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
            text,
        )
        if date_match:
            month_str, day_str, yr_str = date_match.groups()
            month_num = [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ].index(month_str) + 1
            try:
                rel_date = date(int(yr_str), month_num, int(day_str))
            except ValueError:
                pass

        # 季度末交易日
        month_end = q_num * 3
        day_end = 31 if month_end in (3, 12) else 30
        t_date = date(year, month_end, day_end)

        return {
            "report_quarter": report_quarter,
            "trade_date": t_date,
            "global_billings_billion_usd": global_billings,
            "china_billings_billion_usd": china_billings,
            "release_date": rel_date or t_date,
            "source_url": source_url,
        }

    def fetch_latest(self) -> list[dict[str, Any]]:
        """在线抓取 SEMI 官方新闻主页或 PR Newswire 官方镜像并解析最新 WWSEMS 公报。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        sources_to_try = [
            (SEMI_PR_URL, "https://www.semi.org"),
            (
                "https://www.prnewswire.com/news-releases/semi-reports-news-list/",
                "https://www.prnewswire.com",
            ),
        ]

        for url, base_url in sources_to_try:
            try:
                resp = requests.get(url, headers=SEMI_HEADERS, timeout=15, impersonate="chrome120")
                if resp.status_code != 200 or not resp.content:
                    continue

                soup = BeautifulSoup(resp.content, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    if not isinstance(a_tag, Tag):
                        continue
                    title = a_tag.get_text(strip=True)
                    if any(
                        kw in title.lower()
                        for kw in ["equipment billings", "wwsems", "semiconductor equipment market"]
                    ):
                        href = a_tag.get("href")
                        if not isinstance(href, str):
                            continue
                        full_url = href if href.startswith("http") else f"{base_url}{href}"
                        try:
                            art_resp = requests.get(
                                full_url, headers=SEMI_HEADERS, timeout=15, impersonate="chrome120"
                            )
                            if art_resp.status_code == 200:
                                parsed = self.parse_article_text(art_resp.text, source_url=full_url)
                                if parsed:
                                    results.append(parsed)
                        except Exception as e:
                            logger.warning("抓取公报详情失败 [%s]: %s", full_url, e)
                if results:
                    break
            except Exception as exc:
                logger.warning("抓取源异常 [%s]: %s", url, exc)

        return results
